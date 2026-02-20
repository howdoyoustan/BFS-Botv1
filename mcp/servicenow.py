import os
import requests
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

    def _get(self, endpoint: str, params: dict | None = None) -> dict:
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

        return resp.json()

    def get_incident(self, number: str) -> Optional[dict]:
        """Fetch a single incident by its INC number."""
        params = {
            "sysparm_query": f"number={number.upper()}",
            "sysparm_display_value": "true",
            "sysparm_fields": ",".join(INCIDENT_FIELDS),
            "sysparm_limit": 1,
        }
        data = self._get("/api/now/table/incident", params)
        results = data.get("result", [])
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
        data = self._get("/api/now/table/incident", params)
        results = data.get("result", [])

        if results:
            return results

        # Fallback: OR across all keywords (broader)
        or_parts = []
        for kw in keywords:
            or_parts.append(f"short_descriptionLIKE{kw}")
            or_parts.append(f"descriptionLIKE{kw}")

        params["sysparm_query"] = "^OR".join(or_parts)
        data = self._get("/api/now/table/incident", params)
        return data.get("result", [])

    def filter_incidents(
        self,
        query: str,
        limit: int = 20,
        orderby: str = "opened_at",
    ) -> list[dict]:
        """
        Run a raw ServiceNow encoded query (for structured filters
        like priority>3, state=6, etc.).
        """
        params = {
            "sysparm_query": f"{query}^ORDERBY{orderby}",
            "sysparm_display_value": "true",
            "sysparm_fields": ",".join(INCIDENT_FIELDS),
            "sysparm_limit": limit,
        }
        data = self._get("/api/now/table/incident", params)
        return data.get("result", [])

    def create_incident(self, fields: dict) -> dict:
        """Create a new incident. Returns the created record."""
        url = f"{self.base_url}/api/now/table/incident"
        resp = requests.post(
            url, auth=self.auth, headers=self.headers, json=fields
        )
        resp.raise_for_status()
        return resp.json().get("result", {})

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
        data = self._get("/api/now/table/sys_journal_field", params)
        return data.get("result", [])
