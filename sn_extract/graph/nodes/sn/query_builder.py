"""
DEPRECATED — kept for reference only.

SN query generation is now handled by the LLM inside classify.py.
Neither retrieve.py nor disambiguate.py imports this module any longer.

Original purpose: converts accumulated entities dict into a ServiceNow
encoded query string.
"""

from datetime import datetime, timedelta


STATE_MAP = {
    "new": "1", "in_progress": "2", "on_hold": "3",
    "resolved": "6", "closed": "7",
}


def build_sn_query(entities: dict) -> tuple[str, str]:
    """
    Convert an accumulated-entities dict into
    (sn_encoded_query, orderby_field).
    """
    if "incident_id" in entities:
        return f"number={entities['incident_id']}", "opened_at"

    parts: list[str] = []

    # Priority
    priorities = entities.get("priorities")
    if priorities:
        if len(priorities) == 1:
            parts.append(f"priority={priorities[0]}")
        else:
            parts.append("^OR".join(f"priority={p}" for p in priorities))

    # State
    states = entities.get("states")
    if states:
        vals = [STATE_MAP.get(s, s) for s in states]
        if len(vals) == 1:
            parts.append(f"state={vals[0]}")
        else:
            parts.append("^OR".join(f"state={v}" for v in vals))

    # Time range
    time_range = entities.get("time_range")
    if time_range:
        clause = _resolve_time_range(time_range)
        if clause:
            parts.append(clause)

    # Category
    category = entities.get("category")
    if category:
        parts.append(f"category={category}")

    # Assignee / assignment group
    assignee = entities.get("assignee")
    if assignee:
        parts.append(f"assignment_groupLIKE{assignee}")

    # Keyword search
    keywords = entities.get("keywords")
    if keywords:
        for kw in keywords:
            parts.append(f"short_descriptionLIKE{kw}")

    # Ordering
    orderby = "DESCopened_at"
    sort_by = entities.get("sort_by")
    if sort_by == "oldest":
        orderby = "opened_at"
    elif sort_by == "newest":
        orderby = "DESCopened_at"
    elif sort_by == "highest_priority":
        orderby = "priority"
    elif sort_by == "lowest_priority":
        orderby = "DESCpriority"
    elif sort_by == "recently_resolved":
        orderby = "DESCresolved_at"

    query_string = "^".join(parts)
    return query_string, orderby


def _resolve_time_range(value: str) -> str | None:
    now = datetime.now()

    relative = {
        "today":      now.replace(hour=0, minute=0, second=0),
        "yesterday":  (now - timedelta(days=1)).replace(hour=0, minute=0, second=0),
        "last_24h":   now - timedelta(hours=24),
        "last_7d":    now - timedelta(days=7),
        "last_week":  now - timedelta(days=7),
        "last_30d":   now - timedelta(days=30),
        "last_month": now - timedelta(days=30),
    }

    if value in relative:
        dt = relative[value]
        return f"opened_at>={dt.strftime('%Y-%m-%d %H:%M:%S')}"

    if ".." in value:
        start, end = value.split("..", 1)
        return (
            f"opened_at>={start.strip()} 00:00:00"
            f"^opened_at<={end.strip()} 23:59:59"
        )

    try:
        datetime.fromisoformat(value)
        return f"opened_at>={value} 00:00:00^opened_at<={value} 23:59:59"
    except ValueError:
        return None
