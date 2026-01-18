# def de_router(state):
#     return "retrieve"

def de_decide_next_step(state):
    """
    Decision logic after hallucination check.
    """

    # 1. Hallucination → retry generation (max 1)
    if state.get("is_grounded") == "no":
        if state.get("retry_generation_count", 0) < 1:
            return "retry_generate"
        else:
            return "improve_kb"

    # 2. Grounded but insufficient → improve KB (max 3)
    if "I don't know" in state.get("generation", ""):
        if (
            state.get("kb_retry_count", 0) < 3
            and state.get("kb_enriched", True)
        ):
            return "improve_kb"
        else:
            return "finalize"

    # 3. Grounded and sufficient
    return "finalize"
