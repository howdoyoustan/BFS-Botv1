"""
Layer 3 — Disambiguation Response Generator

Returns a structured sn_response dict that tells app.py exactly
what interactive widgets to render (pills per dimension with live
counts).  Never returns plain markdown — the UI layer decides
presentation.
"""

from mcp.servicenow import ServiceNowClient

MAX_OPTIONS_PER_DIMENSION = 6

DIMENSION_IMPACT_ORDER = [
    "priorities",
    "time_range",
    "states",
    "category",
    "assignee",
]

DIMENSION_LABELS = {
    "priorities": "Priority",
    "time_range": "Time period",
    "states":     "Status",
    "category":   "Category",
    "assignee":   "Assignment group",
}


def sn_disambiguate_node(state):
    """
    Sample incident store for dimension distributions and return a
    structured response with selectable filter options.
    """
    session = dict(state.get("sn_session") or {})
    entities = session.get("accumulated_entities", {})

    base_query = session.get("sn_query", "")

    client = ServiceNowClient()
    try:
        counts = client.sample_dimensions(base_query)
    except Exception:
        counts = {"total": 0}

    # Fallback: if current filters return 0, sample from all incidents so user can still refine
    total = counts.get("total", 0)
    used_fallback = False
    if total == 0 and base_query:
        try:
            counts = client.sample_dimensions("")
            total = counts.get("total", 0)
            used_fallback = total > 0
        except Exception:
            pass

    session["dimension_counts"] = counts
    session["disambiguation_count"] = session.get("disambiguation_count", 0) + 1

    if total == 0:
        sn_response = {
            "type": "disambiguation",
            "text": "I couldn't find any incidents matching your current filters. Try broader criteria or ask about a specific incident number.",
            "filters": [],
            "metrics": {"total": 0},
        }
    else:
        filter_groups = _build_filter_groups(counts, entities)
        active_text = ""
        if entities:
            active_parts = [
                f"{k}: {v}" for k, v in entities.items()
                if k not in ("sort_by", "limit", "keywords")
            ]
            if active_parts:
                active_text = f"  \nActive filters: {', '.join(active_parts)}"

        if used_fallback:
            intro = f"Your current filters returned no incidents. Here are options from **all {total}** incidents to narrow down:"
        else:
            intro = f"I found **{total}** incidents.{active_text}"

        sn_response = {
            "type": "disambiguation",
            "text": intro,
            "filters": filter_groups,
            "metrics": {"total": total},
        }

    missing = _get_missing_dimensions(entities)
    session["awaiting"] = missing[0] if missing else None

    fallback_md = sn_response["text"]
    if sn_response["filters"]:
        for grp in sn_response["filters"]:
            labels = [f"{o['label']} ({o['count']})" for o in grp["options"]]
            fallback_md += f"\n- **{grp['dimension_label']}**: {', '.join(labels)}"

    return {
        "generation": fallback_md,
        "sn_response": sn_response,
        "sn_session": session,
        "steps": [
            f"sn_disambiguate:total={total}",
            f"sn_disambiguate:round={session['disambiguation_count']}",
        ],
    }


def _get_missing_dimensions(entities: dict) -> list[str]:
    return [d for d in DIMENSION_IMPACT_ORDER if d not in entities]


def _build_filter_groups(counts: dict, entities: dict) -> list[dict]:
    """Build structured filter groups for each unpopulated dimension."""
    missing = _get_missing_dimensions(entities)
    groups = []

    for dim in missing:
        options = _options_for_dimension(dim, counts)
        if options:
            groups.append({
                "dimension": dim,
                "dimension_label": DIMENSION_LABELS.get(dim, dim),
                "options": options,
            })
        if len(groups) >= 4:
            break

    return groups


def _options_for_dimension(dim: str, counts: dict) -> list[dict]:
    """Extract selectable options for a single dimension from sampled counts."""

    if dim == "priorities":
        data = counts.get("priority", {})
        return [
            {"label": k, "count": v, "value": f"priority:{k}"}
            for k, v in list(data.items())[:MAX_OPTIONS_PER_DIMENSION]
        ] if data else []

    if dim == "states":
        data = counts.get("state", {})
        return [
            {"label": k, "count": v, "value": f"state:{k}"}
            for k, v in list(data.items())[:MAX_OPTIONS_PER_DIMENSION]
        ] if data else []

    if dim == "time_range":
        data = counts.get("time_buckets", {})
        value_map = {
            "Today": "today", "Last 7 days": "last_7d",
            "Last 30 days": "last_30d", "Older": "last_30d",
        }
        return [
            {"label": k, "count": v, "value": f"time:{value_map.get(k, 'last_30d')}"}
            for k, v in data.items()
        ] if data else []

    if dim == "category":
        data = counts.get("category", {})
        return [
            {"label": k, "count": v, "value": f"category:{k}"}
            for k, v in list(data.items())[:MAX_OPTIONS_PER_DIMENSION]
        ] if data else []

    if dim == "assignee":
        data = counts.get("assignment_group", {})
        return [
            {"label": k, "count": v, "value": f"assignee:{k}"}
            for k, v in list(data.items())[:MAX_OPTIONS_PER_DIMENSION]
        ] if data else []

    return []
