"""
Layer 2 — Specificity Scoring

Pure deterministic logic — no LLM calls.  Scores the accumulated
context against weighted filter dimensions and decides the routing
action.

Intent-aware override: when the user clearly wants results
(fetch_incidents with any populated dimension), execute immediately
instead of forcing disambiguation.  Disambiguation only triggers
for truly bare queries with zero context.

Action intents (acknowledge_incident, assign_incident, update_status)
are routed to the confirmation / execution path instead of the normal
retrieve path.
"""

MAX_DISAMBIGUATION_ROUNDS = 3

DIMENSION_WEIGHTS: dict[str, float] = {
    "incident_id":  1.0,
    "time_range":   0.25,
    "priorities":   0.20,
    "states":       0.15,
    "category":     0.15,
    "keywords":     0.15,
    "sort_by":      0.10,
    "assignee":     0.10,
}

LOW_THRESHOLD = 0.15

EXECUTE_INTENTS = {"fetch_incidents", "get_incident_detail", "get_incident_stats", "search_by_keyword", "force_show"}
ACTION_INTENTS = {
    "acknowledge_incident",
    "add_work_notes",
    "assign_incident",
    "escalate_priority",
    "update_status",
    "resolve_incident",
    "link_related_incidents",
}


def sn_score_node(state):
    """Score accumulated entities and decide: disambiguate, execute, or confirm action."""
    session = dict(state.get("sn_session") or {})
    entities = session.get("accumulated_entities", {})
    sn_intent = session.get("sn_intent", "")
    round_count = session.get("disambiguation_count", 0)

    score = _compute_score(entities)
    session["specificity_score"] = score

    if sn_intent in ACTION_INTENTS:
        if session.get("action_confirmed"):
            action = "execute_action"
        else:
            action = "confirm_action"
    elif "incident_id" in entities:
        action = "execute"
    elif sn_intent == "get_incident_stats":
        action = "execute"
    elif sn_intent in EXECUTE_INTENTS and score > 0:
        action = "execute"
    elif score >= LOW_THRESHOLD:
        action = "execute"
    elif round_count >= MAX_DISAMBIGUATION_ROUNDS:
        action = "force_execute"
    else:
        action = "disambiguate"

    session["sn_action"] = action

    return {
        "sn_session": session,
        "steps": [f"sn_score:{score:.2f}", f"sn_score:action={action}"],
    }


def _compute_score(entities: dict) -> float:
    score = 0.0
    for dim, weight in DIMENSION_WEIGHTS.items():
        if dim in entities and entities[dim] is not None:
            score += weight
    return min(score, 1.0)
