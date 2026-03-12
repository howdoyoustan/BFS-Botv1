"""
ServiceNow result generator.

Returns a structured sn_response dict so app.py can render incidents
interactively (selectable table, detail card) instead of static markdown.
Also sets a markdown fallback in `generation` for non-SN renderers.

Handles three response shapes:
  - single_incident   (1 result)
  - incident_list     (multiple results, with real total from count query)
  - incident_stats    (get_incident_stats intent — count-focused response)
"""

from collections import Counter

from mcp.servicenow import ServiceNowClient
from graph.nodes.sn.disambiguate import _build_filter_groups


def sn_generate_node(state):
    """Build structured response from retrieved incidents."""
    incidents = state.get("sn_incidents", [])
    session = dict(state.get("sn_session") or {})
    sn_intent = session.get("sn_intent", "fetch_incidents")
    total_count = session.get("sn_total_count", len(incidents))

    if not incidents and total_count == 0:
        if state.get("generation", "").startswith("ServiceNow API error"):
            return {"steps": ["sn_generate:api_error"]}

        # Match disambiguation UX: when strict filters yield nothing, offer
        # refinement options sampled from the broader incident population.
        entities = session.get("accumulated_entities", {})
        fallback_counts = {"total": 0}
        try:
            fallback_counts = ServiceNowClient().sample_dimensions("")
        except Exception:
            pass

        fallback_total = fallback_counts.get("total", 0)
        if fallback_total > 0:
            filter_groups = _build_filter_groups(fallback_counts, entities)
            sn_response = {
                "type": "disambiguation",
                "text": (
                    f"Your current filters returned no incidents. Here are options from "
                    f"all **{fallback_total}** incidents to narrow down:"
                ),
                "filters": filter_groups,
                "metrics": {"total": fallback_total},
            }
            session["dimension_counts"] = fallback_counts
            session["disambiguation_count"] = session.get("disambiguation_count", 0) + 1
            return {
                "generation": sn_response["text"],
                "sn_response": sn_response,
                "sn_session": session,
                "steps": ["sn_generate:no_incidents:fallback_disambiguation"],
            }

        sn_response = {
            "type": "incident_list",
            "text": "No incidents found matching your filters.",
            "incidents": [],
            "metrics": {"total": 0},
        }
        return {
            "generation": sn_response["text"],
            "sn_response": sn_response,
            "sn_session": session,
            "steps": ["sn_generate:no_incidents"],
        }

    session["awaiting"] = None
    session["disambiguation_count"] = 0

    if sn_intent == "get_incident_stats":
        sn_response, fallback = _build_stats_response(
            incidents, total_count, session,
        )
    elif len(incidents) == 1 and total_count == 1:
        inc = incidents[0]
        sn_response = {
            "type": "single_incident",
            "text": f"Incident {inc.get('number', 'N/A')}",
            "incident": inc,
        }
        fallback = _format_single_incident(inc)
    else:
        metrics = _build_metrics(incidents, total_count)
        compact = [_compact_incident(i) for i in incidents]
        showing = len(incidents)
        if total_count > showing:
            text = f"Showing **{showing}** of **{total_count}** incidents."
        else:
            text = f"Found **{total_count}** incidents."
        sn_response = {
            "type": "incident_list",
            "text": text,
            "incidents": compact,
            "metrics": metrics,
        }
        fallback = _format_incident_list_md(incidents, metrics)

    return {
        "generation": fallback,
        "sn_response": sn_response,
        "sn_session": session,
        "steps": [f"sn_generate:{sn_intent}:{len(incidents)}_of_{total_count}"],
    }


# ── Stats response builder ──────────────────────────────────────────

def _build_stats_response(
    incidents: list[dict], total_count: int, session: dict,
) -> tuple[dict, str]:
    """Build a count/stats-focused response with optional sample breakdown."""
    entities = session.get("accumulated_entities", {})

    filter_parts = []
    if entities.get("states"):
        filter_parts.append(f"state: {', '.join(entities['states'])}")
    if entities.get("priorities"):
        filter_parts.append(f"priority: {', '.join(str(p) for p in entities['priorities'])}")
    if entities.get("time_range"):
        filter_parts.append(f"time: {entities['time_range']}")
    if entities.get("category"):
        filter_parts.append(f"category: {entities['category']}")

    filter_desc = f" ({', '.join(filter_parts)})" if filter_parts else ""

    text = f"There are **{total_count}** incidents{filter_desc}."

    metrics = _build_metrics(incidents, total_count) if incidents else {"total": total_count}
    compact = [_compact_incident(i) for i in incidents]

    sn_response = {
        "type": "incident_stats",
        "text": text,
        "incidents": compact,
        "metrics": metrics,
    }

    fallback_lines = [text]
    if incidents:
        fallback_lines.append("\nSample:")
        for inc in incidents[:5]:
            fallback_lines.append(
                f"- **{inc.get('number', 'N/A')}** | "
                f"{inc.get('state', '')} | "
                f"P{inc.get('priority', '?')} | "
                f"{inc.get('opened_at', '')[:10]} | "
                f"{inc.get('short_description', '')}"
            )

    return sn_response, "\n".join(fallback_lines)


# ── Helpers ──────────────────────────────────────────────────────────

def _compact_incident(inc: dict) -> dict:
    """Slim dict for the incident list table."""
    return {
        "number": inc.get("number", ""),
        "short_description": inc.get("short_description", ""),
        "priority": inc.get("priority", ""),
        "state": inc.get("state", ""),
        "category": inc.get("category", ""),
        "opened_at": inc.get("opened_at", "")[:16],
        "assigned_to": inc.get("assigned_to", ""),
    }


def _build_metrics(incidents: list[dict], total_count: int | None = None) -> dict:
    priorities = Counter(inc.get("priority", "?") for inc in incidents)
    states = Counter(inc.get("state", "?") for inc in incidents)
    dates = [inc.get("opened_at", "")[:10] for inc in incidents if inc.get("opened_at")]

    return {
        "total": total_count if total_count is not None else len(incidents),
        "by_priority": dict(priorities.most_common()),
        "by_state": dict(states.most_common()),
        "date_range": f"{min(dates)} to {max(dates)}" if dates else "",
    }


# ── Markdown fallbacks (for non-SN renderers / chat history) ────────

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


def _format_incident_list_md(incidents: list[dict], metrics: dict) -> str:
    total = metrics["total"]
    showing = len(incidents)
    if total > showing:
        lines = [f"## Showing {showing} of {total} Incidents", ""]
    else:
        lines = [f"## Found {total} Incidents", ""]

    pri_str = ", ".join(f"P{k}: {v}" for k, v in metrics["by_priority"].items())
    if pri_str:
        lines.append(f"**By Priority:** {pri_str}")
    state_str = ", ".join(f"{k}: {v}" for k, v in metrics["by_state"].items())
    if state_str:
        lines.append(f"**By State:** {state_str}")
    if metrics.get("date_range"):
        lines.append(f"**Date Range:** {metrics['date_range']}")

    lines.append("")
    for inc in incidents[:20]:
        lines.append(
            f"- **{inc.get('number', 'N/A')}** | "
            f"{inc.get('state', '')} | "
            f"P{inc.get('priority', '?')} | "
            f"{inc.get('opened_at', '')[:10]} | "
            f"{inc.get('short_description', '')}"
        )
    if showing < total:
        lines.append(f"\n*...and {total - showing} more.*")

    return "\n".join(lines)
