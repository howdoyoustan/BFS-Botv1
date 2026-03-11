"""
ServiceNow Action Execution Node

Reads the pending_action from the session (placed there by sn_confirm)
and executes the corresponding PATCH call against the ServiceNow API.
Only runs after the user has explicitly confirmed the action.
"""

from mcp.servicenow import ServiceNowClient


def sn_execute_action_node(state):
    """Execute the confirmed action against ServiceNow."""
    session = dict(state.get("sn_session") or {})
    pending = session.get("pending_action")

    if not pending:
        return {
            "generation": "No pending action to execute.",
            "sn_session": session,
            "steps": ["sn_execute_action:no_pending"],
        }

    sys_id = pending["sys_id"]
    changes = pending["changes"]
    inc_number = pending.get("incident_number", "unknown")
    action_type = pending.get("type", "unknown")

    client = ServiceNowClient()
    try:
        updated = client.update_incident(sys_id, changes)
    except Exception as exc:
        session.pop("pending_action", None)
        session["awaiting"] = None
        return {
            "generation": f"Failed to execute action on **{inc_number}**: {exc}",
            "sn_session": session,
            "steps": [f"sn_execute_action:error:{type(exc).__name__}"],
        }

    session.pop("pending_action", None)
    session["awaiting"] = None
    session["action_confirmed"] = False

    _action_success_text = {
        "acknowledge_incident": "has been acknowledged successfully.",
        "resolve_incident": "has been resolved successfully.",
    }
    success_text = _action_success_text.get(
        action_type, "has been updated successfully."
    )

    sn_response = {
        "type": "action_result",
        "success": True,
        "action_type": action_type,
        "text": f"**{inc_number}** {success_text}",
        "incident": {
            "number": updated.get("number", inc_number),
            "short_description": updated.get("short_description", ""),
            "state": updated.get("state", ""),
            "priority": updated.get("priority", ""),
            "assigned_to": updated.get("assigned_to", ""),
            "assignment_group": updated.get("assignment_group", ""),
            "opened_at": updated.get("opened_at", ""),
        },
    }

    return {
        "generation": sn_response["text"],
        "sn_response": sn_response,
        "sn_session": session,
        "steps": [
            f"sn_execute_action:{action_type}",
            f"sn_execute_action:success:{inc_number}",
        ],
    }
