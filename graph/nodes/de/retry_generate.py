def de_retry_generate_node(state):
    retry_count = state.get("retry_generation_count", 0) + 1

    return {
        "retry_generation_count": retry_count,
        "steps": [f"de_retry_generate:{retry_count}"]
    }
