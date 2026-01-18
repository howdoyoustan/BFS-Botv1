def gt_generate_node(state):
    used_llm_fallback = not bool(state.get("documents"))

    return {
        "generation": "Heuristic troubleshooting answer",
        "gt_used_llm_fallback": used_llm_fallback,
        "steps": [f"gt_generate:fallback={used_llm_fallback}"]
    }
