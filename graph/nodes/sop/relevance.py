def sop_relevance_node(state):
    docs = state.get("documents", [])

    if not docs:
        return {
            "is_relevant": "no",
            "steps": ["sop_relevance:no_docs"]
        }

    # SOPs are high-signal → retrieval hit is usually enough
    return {
        "is_relevant": "yes",
        "steps": ["sop_relevance:yes"]
    }
