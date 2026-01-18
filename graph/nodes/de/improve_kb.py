def de_improve_kb_node(state):
    kb_retry_count = state.get("kb_retry_count", 0) + 1

    # placeholder until real logic is wired
    kb_enriched = False

    return {
        "kb_retry_count": kb_retry_count,
        "kb_enriched": kb_enriched,
        "steps": [f"de_improve_kb:{kb_retry_count}"]
    }
