"""
Layer 4 — Context Accumulator

Merges entity extractions across turns into a single accumulated
context.  On each turn the latest entities overwrite the corresponding
dimension (not append), so the user can correct earlier choices.

Also decides whether this is a brand-new query or a continuation.
"""


def sn_accumulate_node(state):
    """Merge this turn's extracted entities into the session context."""
    session = dict(state.get("sn_session") or {})
    turn_entities = session.pop("_turn_entities", {})
    sn_intent = session.get("sn_intent", "fetch_incidents")

    accumulated = dict(session.get("accumulated_entities", {}))

    is_new_query = sn_intent not in ("clarify",) and not session.get("awaiting")
    if is_new_query:
        accumulated = {}
        session["disambiguation_count"] = 0

    # Merge: new values overwrite old for the same dimension
    for key, value in turn_entities.items():
        accumulated[key] = value

    session["accumulated_entities"] = accumulated
    session["awaiting"] = None  # clear — we're processing now

    return {
        "sn_session": session,
        "steps": [
            f"sn_accumulate:{'new' if is_new_query else 'merge'}",
            f"sn_accumulate:dims={list(accumulated.keys())}",
        ],
    }
