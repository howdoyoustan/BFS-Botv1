"""
ServiceNow incident retrieval.

Uses the LLM-generated sn_query and sn_orderby from the classifier
session instead of the deterministic query_builder.  Also handles
get_incident_stats by fetching a count + small sample.
"""

from mcp.servicenow import ServiceNowClient


def sn_retrieve_node(state):
    """
    Execute the ServiceNow query from the session.
    Runs only when the specificity scorer says "execute" or "force_execute".
    """
    session = dict(state.get("sn_session") or {})
    entities = session.get("accumulated_entities", {})
    sn_intent = session.get("sn_intent", "fetch_incidents")

    query_string = session.get("sn_query", "")
    orderby = session.get("sn_orderby", "ORDERBYDESCopened_at")

    client = ServiceNowClient()
    limit = entities.get("limit", 20)

    try:
        inc_id = entities.get("incident_id")

        if inc_id:
            incidents = _lookup_by_number(client, inc_id.upper())
            total_count = len(incidents)
            step = f"sn_retrieve:lookup:{total_count}_incidents"

        elif sn_intent == "get_incident_stats":
            total_count = client.count_incidents(query_string)
            sample_limit = min(limit, 5)
            incidents = client.filter_incidents(
                query_string, orderby=orderby, limit=sample_limit,
            )
            step = f"sn_retrieve:stats:total={total_count},sample={len(incidents)}"

        else:
            total_count = client.count_incidents(query_string)
            incidents = client.filter_incidents(
                query_string, orderby=orderby, limit=limit,
            )
            step = f"sn_retrieve:filter:{len(incidents)}_of_{total_count}"

    except Exception as exc:
        return {
            "sn_incidents": [],
            "generation": f"ServiceNow API error: {exc}",
            "steps": [f"sn_retrieve:error:{type(exc).__name__}"],
        }

    session["sn_total_count"] = total_count

    return {
        "sn_incidents": incidents,
        "sn_session": session,
        "steps": [step],
    }


def _lookup_by_number(client: ServiceNowClient, number: str) -> list[dict]:
    incident = client.get_incident(number)
    if incident:
        work_notes = client.get_work_notes(incident["sys_id"])
        incident["_work_notes_journal"] = work_notes
        return [incident]
    return []
