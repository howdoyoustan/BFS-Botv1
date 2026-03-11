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
    changes = dict(pending.get("changes", {}))
    inc_number = pending.get("incident_number", "unknown")
    action_type = pending.get("type", "unknown")

    client = ServiceNowClient()
    try:
        if action_type == "add_work_notes":
            work_notes = changes.get("work_notes", "").strip()
            if not work_notes:
                return {
                    "generation": "Work notes cannot be empty.",
                    "sn_session": session,
                    "steps": ["sn_execute_action:empty_work_notes"],
                }
            updated = client.append_work_notes(sys_id, work_notes)
        elif action_type == "link_related_incidents":
            parent_sys_id = pending.get("parent_sys_id")
            if parent_sys_id:
                updated = client.link_incidents(sys_id, parent_sys_id)
            else:
                return {
                    "generation": "Missing parent incident for link.",
                    "sn_session": session,
                    "steps": ["sn_execute_action:missing_parent"],
                }
        elif action_type == "escalate_priority":
            target = pending.get("target_priority")
            if not target:
                return {
                    "generation": "Missing target priority for escalation.",
                    "sn_session": session,
                    "steps": ["sn_execute_action:missing_target"],
                }
            client.escalate_incident(sys_id, target)
            # Re-fetch so we get the recalculated priority (ServiceNow derives it from impact+urgency)
            updated = client.get_incident(inc_number) or {}
        else:
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
        "add_work_notes": "work note has been added successfully.",
        "assign_incident": "has been reassigned successfully.",
        "escalate_priority": "priority has been escalated successfully.",
        "resolve_incident": "has been resolved successfully.",
        "link_related_incidents": "has been linked successfully.",
    }
    success_text = _action_success_text.get(
        action_type, "has been updated successfully."
    )

    inc_data = updated if isinstance(updated, dict) else {}
    sn_response = {
        "type": "action_result",
        "success": True,
        "action_type": action_type,
        "text": f"**{inc_number}** {success_text}",
        "incident": {
            "number": inc_data.get("number", inc_number),
            "short_description": inc_data.get("short_description", ""),
            "state": inc_data.get("state", ""),
            "priority": inc_data.get("priority", ""),
            "assigned_to": inc_data.get("assigned_to", ""),
            "assignment_group": inc_data.get("assignment_group", ""),
            "opened_at": inc_data.get("opened_at", ""),
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
