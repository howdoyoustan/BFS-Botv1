"""
ServiceNow Action Confirmation Node

Fetches the target incident and builds a structured confirmation
response so the UI can show a "Confirm / Cancel" card before any
write operation is executed.

Currently supports:
  - acknowledge_incident  (set state → In Progress)

Extensible for: assign_incident, update_status, resolve, escalate.
"""

from mcp.servicenow import ServiceNowClient

ACTION_DEFINITIONS = {
    "acknowledge_incident": {
        "label": "Acknowledge Incident",
        "description": "Set the incident state to **In Progress** and take ownership.",
        "changes": {"state": "2"},
        "change_summary": ["State → In Progress"],
    },
    "resolve_incident": {
        "label": "Resolve Incident",
        "description": "Set the incident state to **Resolved**. You must provide resolution notes.",
        "changes": {"state": "6"},
        "change_summary": ["State → Resolved", "Close code (required)", "Close notes (required)"],
        "requires_close_notes": True,
    },
}


def sn_confirm_node(state):
    """Build a confirmation card for the pending action."""
    session = dict(state.get("sn_session") or {})
    entities = session.get("accumulated_entities", {})
    sn_intent = session.get("sn_intent", "")

    inc_id = entities.get("incident_id")

    action_def = ACTION_DEFINITIONS.get(sn_intent)
    if not action_def:
        return {
            "generation": f"Action **{sn_intent}** is not supported yet.",
            "sn_session": session,
            "steps": [f"sn_confirm:unsupported_action:{sn_intent}"],
        }

    if not inc_id:
        session["awaiting"] = "incident_id"
        sn_response = {
            "type": "action_needs_input",
            "text": f"Which incident would you like to **{action_def['label'].lower()}**? Please provide the INC number.",
            "awaiting": "incident_id",
        }
        return {
            "generation": sn_response["text"],
            "sn_response": sn_response,
            "sn_session": session,
            "steps": ["sn_confirm:awaiting_incident_id"],
        }

    client = ServiceNowClient()
    try:
        incident = client.get_incident(inc_id.upper())
    except Exception as exc:
        return {
            "generation": f"Could not fetch incident {inc_id}: {exc}",
            "steps": [f"sn_confirm:error:{type(exc).__name__}"],
        }

    if not incident:
        return {
            "generation": f"Incident **{inc_id}** was not found in ServiceNow.",
            "sn_session": session,
            "steps": ["sn_confirm:not_found"],
        }

    pending_action = {
        "type": sn_intent,
        "sys_id": incident["sys_id"],
        "incident_number": incident.get("number", inc_id),
        "changes": action_def["changes"],
        "change_summary": action_def["change_summary"],
        "incident_snapshot": {
            "number": incident.get("number", ""),
            "short_description": incident.get("short_description", ""),
            "state": incident.get("state", ""),
            "priority": incident.get("priority", ""),
            "assigned_to": incident.get("assigned_to", ""),
            "assignment_group": incident.get("assignment_group", ""),
            "opened_at": incident.get("opened_at", ""),
        },
    }

    session["pending_action"] = pending_action
    session["awaiting"] = "action_confirmation"

    close_codes = []
    if action_def.get("requires_close_notes"):
        try:
            close_codes = client.get_close_codes()
        except Exception:
            pass

    sn_response = {
        "type": "action_confirm",
        "text": f"**{action_def['label']}** — {incident.get('number', inc_id)}",
        "action_label": action_def["label"],
        "action_type": sn_intent,
        "action_description": action_def["description"],
        "change_summary": action_def["change_summary"],
        "incident": pending_action["incident_snapshot"],
        "requires_close_notes": action_def.get("requires_close_notes", False),
        "close_codes": close_codes,
    }

    summary_lines = [
        f"**{action_def['label']}** — {incident.get('number', inc_id)}",
        f"_{incident.get('short_description', '')}_",
        "",
        action_def["description"],
        "",
        "Changes:",
    ]
    for change in action_def["change_summary"]:
        summary_lines.append(f"  - {change}")
    summary_lines.append("\nPlease **confirm** or **cancel** this action.")

    return {
        "generation": "\n".join(summary_lines),
        "sn_response": sn_response,
        "sn_session": session,
        "steps": [
            f"sn_confirm:action={sn_intent}",
            f"sn_confirm:incident={incident.get('number', inc_id)}",
        ],
    }
