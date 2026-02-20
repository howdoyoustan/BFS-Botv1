def sn_generate_node(state):
    """
    Format ServiceNow incident data into a readable response.
    Future: add an LLM call here to summarise root cause.
    """
    incidents = state.get("sn_incidents", [])

    if not incidents:
        if state.get("generation", "").startswith("ServiceNow API error"):
            return {"steps": ["sn_generate:api_error"]}
        return {
            "generation": "No incidents found matching your query.",
            "steps": ["sn_generate:no_incidents"],
        }

    if len(incidents) == 1:
        answer = _format_single_incident(incidents[0])
    else:
        answer = _format_incident_list(incidents)

    return {
        "generation": answer,
        "steps": ["sn_generate"],
    }


def _format_single_incident(inc: dict) -> str:
    lines = [
        f"## Incident {inc.get('number', 'N/A')}",
        "",
        f"**Short Description:** {inc.get('short_description', 'N/A')}",
        f"**State:** {inc.get('state', 'N/A')}",
        f"**Priority:** {inc.get('priority', 'N/A')}",
        f"**Impact:** {inc.get('impact', 'N/A')}",
        f"**Urgency:** {inc.get('urgency', 'N/A')}",
        f"**Category:** {inc.get('category', 'N/A')}",
        f"**Assigned To:** {inc.get('assigned_to', 'N/A')}",
        f"**Assignment Group:** {inc.get('assignment_group', 'N/A')}",
        f"**Opened:** {inc.get('opened_at', 'N/A')}",
        f"**Resolved:** {inc.get('resolved_at', 'N/A')}",
        "",
        "### Description",
        inc.get("description", "No description available.") or "N/A",
    ]

    work_notes = inc.get("_work_notes_journal", [])
    if work_notes:
        lines += ["", "### Work Notes"]
        for note in work_notes:
            ts = note.get("sys_created_on", "")
            by = note.get("sys_created_by", "")
            val = note.get("value", "").strip()
            lines.append(f"- **{ts}** ({by}): {val}")

    close_notes = inc.get("close_notes", "")
    if close_notes:
        lines += ["", "### Close Notes", close_notes]

    return "\n".join(lines)


def _format_incident_list(incidents: list[dict]) -> str:
    lines = [f"## Found {len(incidents)} Incidents", ""]
    for inc in incidents:
        pri = inc.get("priority", "?")
        lines.append(
            f"- **{inc.get('number', 'N/A')}** | "
            f"{inc.get('state', '')} | "
            f"P{pri} | "
            f"{inc.get('short_description', 'No description')}"
        )

    lines += [
        "",
        "Ask about a specific incident number "
        "(e.g. INC0010001) for full details including work notes.",
    ]
    return "\n".join(lines)
