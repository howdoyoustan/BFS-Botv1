import os
import requests
from collections import Counter
from typing import Optional
from dotenv import load_dotenv

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
            params["sysparm_query"] = query
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
                stats_params["sysparm_query"] = query
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
        """Look up user sys_id by user_name (LIKE match)."""
        params = {
            "sysparm_query": f"user_nameLIKE{user_name}",
            "sysparm_fields": "sys_id",
            "sysparm_limit": 1,
        }
        try:
            resp = self._get("/api/now/table/sys_user", params)
            results = resp.json().get("result", [])
            return results[0]["sys_id"] if results else None
        except Exception:
            return None

    def get_group_sys_id(self, group_name: str) -> Optional[str]:
        """Look up group sys_id by name (LIKE match)."""
        escaped = group_name.replace("^", "^^").replace(":", "^:")
        params = {
            "sysparm_query": f"nameLIKE{escaped}",
            "sysparm_fields": "sys_id",
            "sysparm_limit": 1,
        }
        try:
            resp = self._get("/api/now/table/sys_user_group", params)
            results = resp.json().get("result", [])
            return results[0]["sys_id"] if results else None
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
            "sysparm_query": base_query or "ORDERBYDESCopened_at",
            "sysparm_display_value": "true",
            "sysparm_fields": ",".join(self.SAMPLE_FIELDS),
            "sysparm_limit": sample_limit,
        }
        resp = self._get("/api/now/table/incident", params)
        rows = resp.json().get("result", [])

        counts: dict = {"total": len(rows)}
        for field in ("priority", "state", "category", "assignment_group"):
            counter = Counter(
                r.get(field, "") for r in rows if r.get(field)
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
            if not opened:
                continue
            try:
                dt = datetime.strptime(opened[:19], "%Y-%m-%d %H:%M:%S")
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
