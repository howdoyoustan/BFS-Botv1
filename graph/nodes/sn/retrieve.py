import re
from mcp.servicenow import ServiceNowClient

INC_PATTERN = re.compile(r"INC\d{4,10}", re.IGNORECASE)

SEARCH_STOP_WORDS = {
    "what", "is", "the", "how", "do", "i", "a", "an", "to", "for",
    "of", "in", "on", "can", "you", "me", "my", "about", "tell",
    "show", "find", "get", "search", "incident", "incidents",
    "servicenow", "snow", "ticket", "tickets", "all", "list",
    "give", "fetch", "pull", "details", "info", "information",
    "which", "that", "have", "has", "with", "are", "was", "were",
    "been", "many", "much", "than", "them", "their", "there",
    "please", "could", "would",
}

# ServiceNow field names — never text-search for these
SN_FIELD_NAMES = {
    "state", "priority", "impact", "urgency", "category",
    "assigned", "assignment", "opened", "resolved", "closed",
}

# ── Structured filter patterns ───────────────────────────────────────

PRIORITY_PATTERNS = [
    (re.compile(r"priority\s*(?:greater than|>|above|higher than)\s*(\d)", re.I),
     lambda m: f"priority>{m.group(1)}"),
    (re.compile(r"priority\s*(?:less than|<|below|lower than)\s*(\d)", re.I),
     lambda m: f"priority<{m.group(1)}"),
    (re.compile(r"priority\s*(?:=|equals?|is)\s*(\d)", re.I),
     lambda m: f"priority={m.group(1)}"),
    (re.compile(r"\bhigh(?:est)?\s*priority\b", re.I),
     lambda _: "priority<=2"),
    (re.compile(r"\blow(?:est)?\s*priority\b", re.I),
     lambda _: "priority>=3"),
    (re.compile(r"\bp([1-4])\b", re.I),
     lambda m: f"priority={m.group(1)}"),
    (re.compile(r"\bpriority\s+([1-5])\b", re.I),
     lambda m: f"priority={m.group(1)}"),
]

STATE_PATTERNS = [
    (re.compile(r"\b(?:resolved|solved|fixed)\b", re.I), "state=6"),
    (re.compile(r"\b(?:closed)\b", re.I), "state=7"),
    (re.compile(r"\b(?:open|new)\b", re.I), "state=1"),
    (re.compile(r"\b(?:in\s*progress)\b", re.I), "state=2"),
    (re.compile(r"\b(?:on\s*hold)\b", re.I), "state=3"),
]

# "highest/lowest <field>" → sort by that field
SUPERLATIVE_PATTERNS = [
    (re.compile(r"\b(?:highest|maximum|max|greatest)\s+(?:state)\b", re.I), "DESCstate"),
    (re.compile(r"\b(?:lowest|minimum|min|least)\s+(?:state)\b", re.I), "state"),
    (re.compile(r"\b(?:highest|maximum|max|greatest)\s+(?:priority)\b", re.I), "priority"),
    (re.compile(r"\b(?:lowest|minimum|min|least)\s+(?:priority)\b", re.I), "DESCpriority"),
    (re.compile(r"\b(?:highest|maximum|max|greatest)\s+(?:impact)\b", re.I), "impact"),
    (re.compile(r"\b(?:highest|maximum|max|greatest)\s+(?:urgency)\b", re.I), "urgency"),
]

ORDER_PATTERNS = [
    (re.compile(r"\b(?:solved|resolved|fixed)\s+(?:earliest|first|oldest)\b", re.I), "resolved_at"),
    (re.compile(r"\b(?:solved|resolved|fixed)\s+(?:latest|last|newest|recently)\b", re.I), "DESCresolved_at"),
    (re.compile(r"\b(?:recently\s+resolved|recently\s+solved|recently\s+closed)\b", re.I), "DESCresolved_at"),
    (re.compile(r"\b(?:earliest|oldest|first)\b", re.I), "opened_at"),
    (re.compile(r"\b(?:latest|newest|most recent|last)\b", re.I), "DESCopened_at"),
]


def sn_retrieve_node(state):
    """
    Deterministic retrieval from ServiceNow.
    - INC number        -> single incident lookup + work notes
    - Structured filter -> priority / state / ordering / superlative queries
    - Text keywords     -> keyword search (AND logic with field-group OR fallback)
    """
    question = state["question"]
    client = ServiceNowClient()

    match = INC_PATTERN.search(question)

    try:
        if match:
            incidents = _lookup_by_number(client, match.group(0).upper())
            step = f"sn_retrieve:lookup:{len(incidents)}_incidents"
        else:
            filters, orderby = _detect_structured_filters(question)

            if filters or orderby != "opened_at":
                query = "^".join(filters) if filters else ""
                incidents = client.filter_incidents(query, orderby=orderby)
                step = f"sn_retrieve:filter:{len(incidents)}_incidents"
            else:
                keywords = _extract_keywords(question)
                incidents = client.search_incidents(keywords) if keywords else []
                step = f"sn_retrieve:search:{len(incidents)}_incidents"

    except Exception as exc:
        return {
            "sn_incidents": [],
            "generation": f"ServiceNow API error: {exc}",
            "steps": [f"sn_retrieve:error:{type(exc).__name__}"],
        }

    return {
        "sn_incidents": incidents,
        "steps": [step],
    }


def _lookup_by_number(client: ServiceNowClient, number: str) -> list[dict]:
    incident = client.get_incident(number)
    if incident:
        work_notes = client.get_work_notes(incident["sys_id"])
        incident["_work_notes_journal"] = work_notes
        return [incident]
    return []


def _detect_structured_filters(question: str) -> tuple[list[str], str]:
    """
    Parse the question for structured ServiceNow filters.
    Returns (filter_conditions, orderby_field).
    """
    filters = []
    orderby = "opened_at"

    for pattern, builder in PRIORITY_PATTERNS:
        m = pattern.search(question)
        if m:
            filters.append(builder(m) if callable(builder) else builder)
            break

    for pattern, state_filter in STATE_PATTERNS:
        if pattern.search(question):
            filters.append(state_filter)
            break

    # Superlative patterns ("highest state", "lowest priority") → treated as orderby
    for pattern, order_field in SUPERLATIVE_PATTERNS:
        if pattern.search(question):
            orderby = order_field
            filters.append("")  # ensure we take the filter path even with no conditions
            break

    if not any(f for f in filters):
        filters = []
        for pattern, order_field in ORDER_PATTERNS:
            if pattern.search(question):
                orderby = order_field
                break

    # Clean empty strings from filters
    filters = [f for f in filters if f]

    return filters, orderby


def _extract_keywords(question: str) -> list[str]:
    """
    Extract individual search-worthy keywords from the question.
    Filters out SN field names to prevent false matches.
    """
    cleaned = re.sub(r"[?!.,;:\"'()]", "", question.lower())
    words = cleaned.split()
    keywords = [
        w for w in words
        if w not in SEARCH_STOP_WORDS
        and w not in SN_FIELD_NAMES
        and len(w) > 2
    ]
    return keywords
