import os
import re
import requests
from collections import Counter
from typing import Optional
from dotenv import load_dotenv


def _sanitize_query_spaces(query: str) -> str:
    """Wrap unquoted LIKE values containing spaces in single quotes (ServiceNow requirement)."""
    if not query:
        return query
    for pattern in [
        r"(assignment_group\.nameLIKE)([^'^]+?)(?=\^|$)",
        r"(assigned_to\.nameLIKE)([^'^]+?)(?=\^|$)",
        r"(caller_id\.nameLIKE)([^'^]+?)(?=\^|$)",
    ]:
        def repl(m):
            val = m.group(2).strip()
            if val and " " in val and not (val.startswith("'") and val.endswith("'")):
                return m.group(1) + "'" + val + "'"
            return m.group(0)

        query = re.sub(pattern, repl, query)
    return query


def _strip_outer_quotes(value: str) -> str:
    value = (value or "").strip()
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1].strip()
    return value


def _normalize_name(value: str) -> str:
    value = _strip_outer_quotes(value).lower()
    # Normalize separators so "Data-Engineering" and "Data Engineering" rank similarly.
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _choose_best_name_match(results: list[dict], target: str, name_field: str = "name") -> Optional[str]:
    """Pick the best candidate sys_id from lookup results using simple name ranking."""
    if not results:
        return None

    target_norm = _normalize_name(target)
    if not target_norm:
        return None

    scored: list[tuple[int, str]] = []
    for row in results:
        raw_name = row.get(name_field) or ""
        if isinstance(raw_name, dict):
            raw_name = raw_name.get("display_value", raw_name.get("value", ""))
        name_norm = _normalize_name(str(raw_name))
        if not name_norm:
            continue

        if name_norm == target_norm:
            score = 100
        elif name_norm.startswith(target_norm):
            score = 80
        elif target_norm in name_norm:
            score = 60
        else:
            # Lightweight token overlap ranking for fuzzy team names.
            target_tokens = set(target_norm.split())
            name_tokens = set(name_norm.split())
            overlap = len(target_tokens & name_tokens)
            if overlap == 0:
                continue
            score = 40 + overlap

        sys_id = row.get("sys_id")
        if sys_id:
            scored.append((score, sys_id))

    if not scored:
        return None

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def _resolve_assignment_group_in_query(client, query: str) -> str:
    """
    Replace assignment_group.nameLIKE'X' with assignment_group=sys_id.
    Uses exact sys_id match instead of nameLIKE to avoid encoding/quoting issues with spaces.
    """
    if not query:
        return query
    # Match: assignment_group.nameLIKE'Data Engineering' or assignment_group.nameLIKEData Engineering
    pattern = r"assignment_group\.nameLIKE(?:'([^']*)'|([^'^]+?))(?=\^|$)"
    parts = []
    last_end = 0
    for m in re.finditer(pattern, query):
        parts.append(query[last_end : m.start()])
        grp_name = _strip_outer_quotes((m.group(1) or m.group(2) or "").strip())
        if grp_name:
            sid = client.get_group_sys_id(grp_name)
            if sid:
                parts.append(f"assignment_group={sid}")
            else:
                parts.append(m.group(0))  # keep original if lookup fails
        else:
            parts.append(m.group(0))
        last_end = m.end()
    parts.append(query[last_end:])
    return "".join(parts)

load_dotenv(override=True)

SN_INSTANCE_URL = os.getenv("SERVICENOW_INSTANCE_URL", "").rstrip("/")
SN_USERNAME = os.getenv("SERVICENOW_USERNAME", "")
SN_PASSWORD = os.getenv("SERVICENOW_PASSWORD", "")

INCIDENT_FIELDS = [
    "sys_id",
    "number",
    "short_description",
    "description",
    "state",
    "priority",
    "impact",
    "urgency",
    "category",
    "subcategory",
    "assigned_to",
    "assignment_group",
    "caller_id",
    "opened_at",
    "resolved_at",
    "closed_at",
    "close_notes",
    "work_notes",
]


class ServiceNowClient:
    """Thin wrapper around the ServiceNow Table API (REST)."""

    def __init__(self):
        if not SN_INSTANCE_URL:
            raise ValueError(
                "SERVICENOW_INSTANCE_URL not set — add it to .env"
            )
        self.base_url = SN_INSTANCE_URL
        self.auth = (SN_USERNAME, SN_PASSWORD)
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _get(self, endpoint: str, params: dict | None = None) -> requests.Response:
        url = f"{self.base_url}{endpoint}"
        resp = requests.get(
            url, auth=self.auth, headers=self.headers, params=params,
            timeout=30,
        )
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            raise RuntimeError(
                f"Expected JSON from ServiceNow but got "
                f"Content-Type '{content_type}'. "
                f"This usually means bad credentials or a wrong instance URL "
                f"(the server returned an HTML login page). "
                f"Check SERVICENOW_INSTANCE_URL, SERVICENOW_USERNAME, "
                f"and SERVICENOW_PASSWORD in your .env file."
            )

        if not resp.text.strip():
            raise RuntimeError(
                "ServiceNow returned an empty response body. "
                "Verify the instance URL and credentials in .env."
            )

        return resp

    def get_incident(self, number: str) -> Optional[dict]:
        """Fetch a single incident by its INC number."""
        params = {
            "sysparm_query": f"number={number.upper()}",
            "sysparm_display_value": "true",
            "sysparm_fields": ",".join(INCIDENT_FIELDS),
            "sysparm_limit": 1,
        }
        resp = self._get("/api/now/table/incident", params)
        results = resp.json().get("result", [])
        return results[0] if results else None

    def search_incidents(
        self, keywords: list[str], limit: int = 10
    ) -> list[dict]:
        """
        Search incidents where ALL keywords appear (in either
        short_description or description).

        Uses AND between keywords with ^NQ (new-query OR) to
        check both fields:
          (short_desc LIKE kw1 AND short_desc LIKE kw2)
          OR (desc LIKE kw1 AND desc LIKE kw2)

        Falls back to broader OR search if AND returns nothing.
        """
        if not keywords:
            return []

        # AND within each field, OR across fields via ^NQ
        sd_and = "^".join(f"short_descriptionLIKE{kw}" for kw in keywords)
        desc_and = "^".join(f"descriptionLIKE{kw}" for kw in keywords)
        and_query = f"{sd_and}^NQ{desc_and}"

        params = {
            "sysparm_query": and_query,
            "sysparm_display_value": "true",
            "sysparm_fields": ",".join(INCIDENT_FIELDS),
            "sysparm_limit": limit,
            "sysparm_orderby": "opened_at",
        }
        resp = self._get("/api/now/table/incident", params)
        results = resp.json().get("result", [])

        if results:
            return results

        # Fallback: OR across all keywords (broader)
        or_parts = []
        for kw in keywords:
            or_parts.append(f"short_descriptionLIKE{kw}")
            or_parts.append(f"descriptionLIKE{kw}")

        params["sysparm_query"] = "^OR".join(or_parts)
        resp = self._get("/api/now/table/incident", params)
        return resp.json().get("result", [])

    def filter_incidents(
        self,
        query: str,
        limit: int = 20,
        orderby: str = "ORDERBYDESCopened_at",
    ) -> list[dict]:
        """
        Run a raw ServiceNow encoded query (for structured filters
        like priority>3, state=6, etc.).
        """
        query = _sanitize_query_spaces(query)
        query = _resolve_assignment_group_in_query(self, query)
        if query:
            full_query = f"{query}^{orderby}"
        else:
            full_query = orderby
        params = {
            "sysparm_query": full_query,
            "sysparm_display_value": "true",
            "sysparm_fields": ",".join(INCIDENT_FIELDS),
            "sysparm_limit": limit,
        }
        resp = self._get("/api/now/table/incident", params)
        return resp.json().get("result", [])

    def count_incidents(self, query: str = "") -> int:
        """Return the total number of incidents matching *query*.

        Uses a lightweight request (1 record, minimal fields) and reads
        the X-Total-Count header that ServiceNow returns with paginated
        results.  Falls back to the Aggregate Stats API if the header
        is absent.
        """
        params: dict = {
            "sysparm_fields": "sys_id",
            "sysparm_limit": 1,
            "sysparm_display_value": "true",
            "sysparm_suppress_pagination_header": "false",
        }
        if query:
            q = _sanitize_query_spaces(query)
            q = _resolve_assignment_group_in_query(self, q)
            params["sysparm_query"] = q
        resp = self._get("/api/now/table/incident", params)
        total = resp.headers.get("X-Total-Count")
        if total is not None:
            return int(total)

        try:
            stats_params: dict = {
                "sysparm_count": "true",
                "sysparm_display_value": "true",
            }
            if query:
                q = _sanitize_query_spaces(query)
                q = _resolve_assignment_group_in_query(self, q)
                stats_params["sysparm_query"] = q
            stats_resp = self._get("/api/now/stats/incident", stats_params)
            stats_data = stats_resp.json().get("result", {})
            count_val = stats_data.get("stats", {}).get("count")
            if count_val is not None:
                return int(count_val)
        except Exception:
            pass

        return len(resp.json().get("result", []))

    def update_incident(self, sys_id: str, fields: dict) -> dict:
        """Update an incident by sys_id. Returns the updated record."""
        url = f"{self.base_url}/api/now/table/incident/{sys_id}"
        params = {"sysparm_display_value": "true"}
        resp = requests.patch(
            url, auth=self.auth, headers=self.headers,
            json=fields, params=params, timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("result", {})

    def append_work_notes(self, sys_id: str, text: str) -> dict:
        """Append work notes to an incident. ServiceNow journals the update."""
        return self.update_incident(sys_id, {"work_notes": text})

    # Standard impact/urgency → priority matrix (ServiceNow calculates priority from these)
    PRIORITY_TO_IMPACT_URGENCY = {
        "1": ("1", "1"),   # P1 Critical: impact=1, urgency=1
        "2": ("1", "2"),   # P2 High: impact=1, urgency=2
        "3": ("2", "2"),   # P3 Moderate: impact=2, urgency=2
        "4": ("2", "3"),   # P4 Low: impact=2, urgency=3
        "5": ("3", "3"),   # P5 Planning: impact=3, urgency=3
    }

    def escalate_incident(self, sys_id: str, target_priority: str) -> dict:
        """
        Escalate incident by setting impact and urgency.
        ServiceNow calculates priority from impact+urgency; direct priority PATCH is ignored.
        target_priority: "1" (Critical) through "5" (Planning).
        """
        mapping = self.PRIORITY_TO_IMPACT_URGENCY.get(str(target_priority))
        if not mapping:
            raise ValueError(f"Invalid target priority: {target_priority}. Use 1-5.")
        impact, urgency = mapping
        return self.update_incident(sys_id, {"impact": impact, "urgency": urgency})

    def link_incidents(self, child_sys_id: str, parent_sys_id: str) -> dict:
        """Link child incident to parent via parent_incident field."""
        return self.update_incident(child_sys_id, {"parent_incident": parent_sys_id})

    def get_user_sys_id(self, user_name: str) -> Optional[str]:
        """
        Look up user sys_id by username or display name.
        Uses ranked matching so natural-language assignee filters resolve better.
        """
        raw = _strip_outer_quotes(user_name)
        if not raw:
            return None

        # Query both username and display name; then rank candidates.
        query = f"user_nameLIKE{raw}^ORnameLIKE{raw}"
        params = {
            "sysparm_query": query,
            "sysparm_fields": "sys_id,name,user_name",
            "sysparm_limit": 20,
        }
        try:
            resp = self._get("/api/now/table/sys_user", params)
            results = resp.json().get("result", [])
            # Prefer exact/closest display-name match; fall back to username field.
            sid = _choose_best_name_match(results, raw, name_field="name")
            if sid:
                return sid
            sid = _choose_best_name_match(results, raw, name_field="user_name")
            return sid
        except Exception:
            return None

    def get_group_sys_id(self, group_name: str) -> Optional[str]:
        """
        Look up group sys_id by name with ranking.
        Avoids over-constraining to a bad first LIKE hit.
        """
        escaped = _strip_outer_quotes(group_name).replace("^", "^^").replace(":", "^:")
        if not escaped:
            return None
        params = {
            "sysparm_query": f"nameLIKE{escaped}",
            "sysparm_fields": "sys_id,name",
            "sysparm_limit": 20,
        }
        try:
            resp = self._get("/api/now/table/sys_user_group", params)
            results = resp.json().get("result", [])
            return _choose_best_name_match(results, escaped, name_field="name")
        except Exception:
            return None

    def get_or_create_group(self, group_name: str) -> Optional[str]:
        """Get group sys_id by name; create if not exists. Returns None on failure."""
        sid = self.get_group_sys_id(group_name)
        if sid:
            return sid
        try:
            url = f"{self.base_url}/api/now/table/sys_user_group"
            resp = requests.post(
                url, auth=self.auth, headers=self.headers,
                json={"name": group_name}, timeout=30,
            )
            resp.raise_for_status()
            return resp.json().get("result", {}).get("sys_id")
        except Exception:
            return None

    def create_incident(self, fields: dict) -> dict:
        """Create a new incident. Returns the created record."""
        url = f"{self.base_url}/api/now/table/incident"
        resp = requests.post(
            url, auth=self.auth, headers=self.headers, json=fields
        )
        resp.raise_for_status()
        return resp.json().get("result", {})

    def get_close_codes(self) -> list[dict]:
        """
        Fetch incident close codes (resolution codes) from sys_choice.
        Returns list of {"value": "...", "label": "..."} for use in resolve dropdown.
        Requires personalized_choices role if instance restricts sys_choice access.
        """
        try:
            params = {
                "sysparm_query": "name=incident^element=close_code",
                "sysparm_fields": "value,label",
                "sysparm_order_by": "sequence",
            }
            resp = self._get("/api/now/table/sys_choice", params)
            rows = resp.json().get("result", [])
            return [{"value": r.get("value", ""), "label": r.get("label", r.get("value", ""))} for r in rows if r.get("value")]
        except Exception:
            return []

    def get_work_notes(self, sys_id: str, limit: int = 20) -> list[dict]:
        """Fetch work-notes journal entries for a given incident sys_id."""
        params = {
            "sysparm_query": (
                f"element_id={sys_id}^element=work_notes"
            ),
            "sysparm_display_value": "true",
            "sysparm_fields": "value,sys_created_on,sys_created_by",
            "sysparm_limit": limit,
            "sysparm_orderby": "sys_created_on",
        }
        resp = self._get("/api/now/table/sys_journal_field", params)
        return resp.json().get("result", [])

    # ── Dimension sampling (for disambiguation) ──────────────────────

    SAMPLE_FIELDS = ["priority", "state", "category", "assignment_group", "opened_at"]

    def sample_dimensions(
        self, base_query: str = "", sample_limit: int = 200,
    ) -> dict:
        """
        Fetch a sample of incidents and aggregate counts per dimension.
        Returns a dict like:
          {
            "total": 200,
            "priority": {"1 - Critical": 12, "2 - High": 45, ...},
            "state": {"New": 30, "In Progress": 55, ...},
            "category": {"Network": 40, "Software": 80, ...},
            "assignment_group": {"Team A": 20, ...},
            "time_buckets": {"Today": 5, "Last 7 days": 23, ...},
          }
        """
        params = {
            "sysparm_query": _resolve_assignment_group_in_query(
                self, _sanitize_query_spaces(base_query) or ""
            ) or "ORDERBYDESCopened_at",
            "sysparm_display_value": "true",
            "sysparm_fields": ",".join(self.SAMPLE_FIELDS),
            "sysparm_limit": sample_limit,
        }
        resp = self._get("/api/now/table/incident", params)
        rows = resp.json().get("result", [])

        def _display_val(val):
            """Extract display string from ServiceNow ref/choice field (can be str or dict)."""
            if val is None:
                return ""
            if isinstance(val, dict):
                return val.get("display_value", val.get("value", "")) or ""
            return str(val) if val else ""

        counts: dict = {"total": len(rows)}
        for field in ("priority", "state", "category", "assignment_group"):
            counter = Counter(
                _display_val(r.get(field)) for r in rows if _display_val(r.get(field))
            )
            counts[field] = dict(counter.most_common(8))

        counts["time_buckets"] = self._bucket_dates(rows)
        return counts

    @staticmethod
    def _bucket_dates(rows: list[dict]) -> dict[str, int]:
        """Bucket opened_at values into human-friendly time ranges."""
        from datetime import datetime, timedelta

        now = datetime.now()
        buckets = {
            "Today": 0,
            "Last 7 days": 0,
            "Last 30 days": 0,
            "Older": 0,
        }
        cutoffs = [
            ("Today", now.replace(hour=0, minute=0, second=0)),
            ("Last 7 days", now - timedelta(days=7)),
            ("Last 30 days", now - timedelta(days=30)),
        ]

        for row in rows:
            opened = row.get("opened_at", "")
            if isinstance(opened, dict):
                opened = opened.get("display_value", opened.get("value", ""))
            if not opened:
                continue
            try:
                dt = datetime.strptime(str(opened)[:19], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try:
                    dt = datetime.strptime(opened[:10], "%Y-%m-%d")
                except ValueError:
                    continue

            placed = False
            for label, cutoff in cutoffs:
                if dt >= cutoff:
                    buckets[label] += 1
                    placed = True
                    break
            if not placed:
                buckets["Older"] += 1

        return {k: v for k, v in buckets.items() if v > 0}
