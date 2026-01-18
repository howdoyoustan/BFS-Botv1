import re

# Whitelisted operational commands
ALLOWED_COMMAND_PATTERNS = [
    r"\bdf\b",
    r"\bdu\b",
    r"\bls\b",
    r"\bchmod\b",
    r"\bchown\b",
    r"\bps\b",
    r"\btop\b",
    r"\bfree\b",
]

# Language that signals speculation (reject)
SPECULATIVE_PATTERNS = [
    r"\bprobably\b",
    r"\bmight be\b",
    r"\bmaybe\b",
    r"\bguess\b",
]

# Internal references that must never be stored
INTERNAL_PATTERNS = [
    r"prod[-_]",
    r"internal[-_]",
    r"corp[-_]",
]

def gt_validate_node(state):
    """
    Validates LLM-generated tribal troubleshooting output.
    Returns kb_enriched=True ONLY if safe to store.
    """

    answer = state.get("generation", "").lower()

    # 1. Must contain at least one valid operational command
    has_valid_command = any(
        re.search(pat, answer) for pat in ALLOWED_COMMAND_PATTERNS
    )

    # 2. Must NOT contain speculative language
    has_speculation = any(
        re.search(pat, answer) for pat in SPECULATIVE_PATTERNS
    )

    # 3. Must NOT reference internal systems
    has_internal_refs = any(
        re.search(pat, answer) for pat in INTERNAL_PATTERNS
    )

    is_valid = (
        has_valid_command
        and not has_speculation
        and not has_internal_refs
    )

    return {
        "kb_enriched": is_valid,
        "steps": [f"gt_validate:{'valid' if is_valid else 'invalid'}"]
    }
