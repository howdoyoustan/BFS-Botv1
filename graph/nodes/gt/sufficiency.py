import re

MIN_LENGTH = 40  # characters

ACTION_VERBS = [
    "check",
    "run",
    "verify",
    "inspect",
    "clear",
    "delete",
    "restart",
    "list",
    "use",
]

REFUSAL_PATTERNS = [
    r"\bi don't know\b",
    r"\bcannot determine\b",
    r"\bno information\b",
    r"\bnot sure\b",
]

def gt_sufficiency_node(state):
    """
    Determines whether the GT answer was sufficient for the user.

    Returns:
        "sufficient" | "insufficient"
    """

    answer = state.get("generation", "")
    normalized = answer.lower().strip()

    # 1. Empty or trivial answer
    if not normalized or len(normalized) < MIN_LENGTH:
        return "insufficient"

    # 2. Explicit refusal / uncertainty
    if any(re.search(pat, normalized) for pat in REFUSAL_PATTERNS):
        return "insufficient"

    # 3. Must contain at least one actionable verb
    has_action = any(
        verb in normalized for verb in ACTION_VERBS
    )

    if not has_action:
        return "insufficient"

    return "sufficient"
