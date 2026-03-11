"""
ServiceNow Action Confirmation Node

Fetches the target incident and builds a structured confirmation
response so the UI can show a "Confirm / Cancel" card before any
write operation is executed.

Tier 1 actions: acknowledge, add_work_notes, assign_incident,
escalate_priority, resolve_incident, link_related_incidents.
"""

from mcp.servicenow import ServiceNowClient

ACTION_DEFINITIONS = {
    "acknowledge_incident": {
        "label": "Acknowledge Incident",
        "description": "Set the incident state to **In Progress** and take ownership.",
        "changes": {"state": "2"},
        "change_summary": ["State → In Progress"],
    },
    "add_work_notes": {
        "label": "Add Work Notes",
        "description": "Append a note to the incident journal.",
        "changes": {},
        "change_summary": ["Add work note to journal"],
        "requires_work_notes": True,
    },
    "assign_incident": {
        "label": "Reassign Incident",
        "description": "Change the assignee or assignment group.",
        "changes": {},
        "change_summary": [],  # Filled dynamically from entities
    },
    "escalate_priority": {
        "label": "Escalate Priority",
        "description": "Set incident to a higher priority. ServiceNow uses impact+urgency to calculate priority.",
        "changes": {},
        "change_summary": [],  # Filled dynamically from entities
        "requires_escalate_target": True,
    },
    "resolve_incident": {
        "label": "Resolve Incident",
        "description": "Set the incident state to **Resolved**. You must provide resolution notes.",
        "changes": {"state": "6"},
        "change_summary": ["State → Resolved", "Close code (required)", "Close notes (required)"],
        "requires_close_notes": True,
    },
    "link_related_incidents": {
        "label": "Link Related Incidents",
        "description": "Link this incident as child of another (parent) incident.",
        "changes": {},
        "change_summary": [],  # Filled dynamically
    },
}


def _build_pending_for_action(sn_intent: str, action_def: dict, incident: dict, entities: dict, client: ServiceNowClient) -> dict | None:
    """Build pending_action changes for action types that need entity resolution."""
    inc_id = incident.get("number", "")
    sys_id = incident["sys_id"]

    if sn_intent == "add_work_notes":
        return {
            "type": sn_intent,
            "sys_id": sys_id,
            "incident_number": inc_id,
            "changes": {},
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

    if sn_intent == "assign_incident":
        assignee = entities.get("assignee")
        if not assignee:
            return None
        user_sid = client.get_user_sys_id(assignee)
        group_sid = client.get_group_sys_id(assignee)
        if user_sid:
            return {"type": sn_intent, "sys_id": sys_id, "incident_number": inc_id, "changes": {"assigned_to": user_sid}, "change_summary": [f"Assigned to → {assignee}"]}
        if group_sid:
            return {"type": sn_intent, "sys_id": sys_id, "incident_number": inc_id, "changes": {"assignment_group": group_sid}, "change_summary": [f"Assignment group → {assignee}"]}
        return None

    if sn_intent == "escalate_priority":
        priorities = entities.get("priorities")
        if not priorities:
            return None
        target = str(priorities[0])
        priority_labels = {"1": "P1 Critical", "2": "P2 High", "3": "P3 Moderate", "4": "P4 Low", "5": "P5 Planning"}
        # ServiceNow calculates priority from impact+urgency; store target for escalate_incident()
        return {"type": sn_intent, "sys_id": sys_id, "incident_number": inc_id, "target_priority": target, "changes": {}, "change_summary": [f"Priority → {priority_labels.get(target, f'P{target}')}"]}

    if sn_intent == "link_related_incidents":
        parent_id = entities.get("parent_incident_id")
        child_id = entities.get("child_incident_id") or entities.get("incident_id")
        if not parent_id or not child_id:
            return None
        parent_inc = client.get_incident(parent_id.upper()) if parent_id else None
        child_inc = client.get_incident(child_id.upper()) if child_id else None
        if not parent_inc or not child_inc:
            return None
        return {
            "type": sn_intent,
            "sys_id": child_inc["sys_id"],
            "incident_number": child_inc.get("number", child_id),
            "parent_sys_id": parent_inc["sys_id"],
            "parent_number": parent_inc.get("number", parent_id),
            "changes": {"parent_incident": parent_inc["sys_id"]},
            "change_summary": [f"Link {child_inc.get('number', child_id)} as child of {parent_inc.get('number', parent_id)}"],
        }

    return None


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

    if not inc_id and sn_intent != "link_related_incidents":
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

    if sn_intent == "link_related_incidents":
        parent_id = entities.get("parent_incident_id")
        child_id = entities.get("child_incident_id") or inc_id
        if not parent_id or not child_id:
            session["awaiting"] = "parent_incident_id" if not parent_id else "child_incident_id"
            which = "parent" if not parent_id else "child"
            hint = f"Which incident should be the {which} of {child_id or parent_id or 'the other'}? Please provide the INC number."
            return {
                "generation": hint,
                "sn_response": {"type": "action_needs_input", "text": hint, "awaiting": session["awaiting"]},
                "sn_session": session,
                "steps": ["sn_confirm:awaiting_link_ids"],
            }

    client = ServiceNowClient()
    lookup_id = inc_id or entities.get("child_incident_id") or entities.get("parent_incident_id") or ""
    try:
        incident = client.get_incident(lookup_id.upper()) if lookup_id else None
    except Exception as exc:
        return {
            "generation": f"Could not fetch incident {lookup_id}: {exc}",
            "steps": [f"sn_confirm:error:{type(exc).__name__}"],
        }

    if not incident:
        return {
            "generation": f"Incident **{lookup_id}** was not found in ServiceNow.",
            "sn_session": session,
            "steps": ["sn_confirm:not_found"],
        }

    pending_action = None
    if sn_intent in ("assign_incident", "escalate_priority", "link_related_incidents"):
        pending_action = _build_pending_for_action(sn_intent, action_def, incident, entities, client)
        if not pending_action:
            if sn_intent == "escalate_priority":
                # Show confirm card with priority picker (no target specified)
                pending_action = {
                    "type": sn_intent,
                    "sys_id": incident["sys_id"],
                    "incident_number": incident.get("number", inc_id),
                    "target_priority": None,
                    "changes": {},
                    "change_summary": ["Select target priority below"],
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
            else:
                missing = "assignee" if sn_intent == "assign_incident" else "parent/child IDs"
                session["awaiting"] = missing
                return {
                    "generation": f"To **{action_def['label'].lower()}**, please specify {missing} (e.g. 'assign to Charlie', 'link INC001 to INC002').",
                    "sn_response": {"type": "action_needs_input", "text": f"Please provide {missing}.", "awaiting": missing},
                    "sn_session": session,
                    "steps": [f"sn_confirm:awaiting_{missing}"],
                }
    else:
        base_changes = dict(action_def.get("changes", {}))
        pending_action = {
            "type": sn_intent,
            "sys_id": incident["sys_id"],
            "incident_number": incident.get("number", inc_id),
            "changes": base_changes,
            "change_summary": list(action_def.get("change_summary", [])),
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
        "change_summary": pending_action.get("change_summary", action_def["change_summary"]),
        "incident": pending_action.get("incident_snapshot", {
            "number": incident.get("number", ""),
            "short_description": incident.get("short_description", ""),
            "state": incident.get("state", ""),
            "priority": incident.get("priority", ""),
            "assigned_to": incident.get("assigned_to", ""),
            "assignment_group": incident.get("assignment_group", ""),
            "opened_at": incident.get("opened_at", ""),
        }),
        "requires_close_notes": action_def.get("requires_close_notes", False),
        "requires_work_notes": action_def.get("requires_work_notes", False),
        "requires_escalate_target": action_def.get("requires_escalate_target", False),
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
    for change in pending_action.get("change_summary", []):
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
