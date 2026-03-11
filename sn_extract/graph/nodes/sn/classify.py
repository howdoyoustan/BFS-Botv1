"""
Layer 1 — Intent Classification, Entity Extraction & SN Query Generation

Uses the LLM to classify the user message into a fine-grained SN
sub-intent, extract every filter dimension, AND generate the
ServiceNow encoded query string — all in a single LLM call.
"""

from resources.llm import get_llm
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from typing import Optional, List
import json


# ── Schema ───────────────────────────────────────────────────────────

class SNClassification(BaseModel):
    intent: str = Field(
        description=(
            "One of: fetch_incidents, get_incident_detail, get_incident_stats, "
            "search_by_keyword, acknowledge_incident, assign_incident, "
            "update_status, resolve_incident, help, clarify, greeting, force_show"
        )
    )
    incident_id: Optional[str] = Field(
        default=None,
        description="Specific INC number if mentioned (e.g. INC0010001)"
    )
    priorities: Optional[List[int]] = Field(
        default=None,
        description="Priority values 1-5. P1=1 critical, P2=2 high, P3=3 moderate, P4=4 low, P5=5 planning"
    )
    states: Optional[List[str]] = Field(
        default=None,
        description="Incident states: new, in_progress, on_hold, resolved, closed"
    )
    time_range: Optional[str] = Field(
        default=None,
        description=(
            "Relative: today, yesterday, last_24h, last_7d, last_30d, last_week, last_month. "
            "Or ISO date: 2025-01-15. Or range: 2025-01-01..2025-01-31"
        )
    )
    category: Optional[str] = Field(
        default=None,
        description="Incident category (e.g. network, software, hardware, inquiry, database)"
    )
    assignee: Optional[str] = Field(
        default=None,
        description="Person or team name if the user mentions assignment"
    )
    keywords: Optional[List[str]] = Field(
        default=None,
        description="Domain-specific search terms (e.g. airflow, DAG failure, login error). Exclude generic words."
    )
    sort_by: Optional[str] = Field(
        default=None,
        description="newest, oldest, highest_priority, lowest_priority, recently_resolved"
    )
    limit: Optional[int] = Field(
        default=None,
        description="If user requests a specific count (top 5, last 10)"
    )
    sn_query: Optional[str] = Field(
        default=None,
        description=(
            "ServiceNow encoded query string built from ALL active filters "
            "(accumulated + current turn). Empty string if no filters apply."
        )
    )
    sn_orderby: Optional[str] = Field(
        default=None,
        description=(
            "ServiceNow sort clause. Must be one of: "
            "ORDERBYopened_at, ORDERBYDESCopened_at, ORDERBYpriority, "
            "ORDERBYDESCpriority, ORDERBYDESCresolved_at. "
            "Default: ORDERBYDESCopened_at"
        )
    )


# ── Prompt ───────────────────────────────────────────────────────────

CLASSIFY_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a ServiceNow incident triage assistant.
Given a user message, conversation history, and any active filters from prior turns, do THREE things:

1. CLASSIFY the message into exactly one intent:
   QUERY intents  — fetch_incidents, get_incident_detail, get_incident_stats, search_by_keyword
   ACTION intents — acknowledge_incident, assign_incident, update_status, resolve_incident
   META intents   — help, clarify, greeting, force_show

   Use "force_show" when the user says things like "just show me", "show results", "skip".
   Use "clarify" when the user is answering a bot question (e.g. "P1", "last week").
   Use "get_incident_stats" when the user asks "how many", "count", "total number of", or aggregate questions.
   Use "fetch_incidents" when the user wants to see/list/show incidents.
   Use "resolve_incident" when the user says resolve, close, or mark as resolved.

2. EXTRACT every filter entity you can identify from the message.

3. GENERATE the ServiceNow encoded query string (sn_query) and sort clause (sn_orderby).

─── ENTITY EXTRACTION RULES ───

PRIORITY RULES:
- P1/critical = 1, P2/high = 2, P3/moderate = 3, P4/low = 4, P5/planning = 5
- "high priority" = [1,2]. "critical" = [1].

STATE RULES:
- Map natural language to: new, in_progress, on_hold, resolved, closed
- "still open" / "active" / "unresolved" → ["new", "in_progress"]
- "resolved" / "fixed" / "solved" → ["resolved"]
- "closed" / "done" → ["closed"]

TIME RULES — be generous with temporal expressions:
- "last night" / "yesterday" → yesterday
- "this morning" / "today" → today
- "recently" / "last few days" → last_7d
- "last week" / "past week" → last_7d
- "this week" → last_7d
- "last month" / "past month" → last_30d
- "from 2025" / "in 2025" / "during 2025" → set time_range to "2025-01-01..2025-12-31"
- "from 2024" / "in 2024" → set time_range to "2024-01-01..2024-12-31"
- "so far" / "ever" / "all time" / "total" → do NOT set time_range (leave null)
- "latest" / "newest" / "most recent" → set sort_by to "newest" (NOT time_range)
- "oldest" / "earliest" / "first incident" → set sort_by to "oldest"
- "first incident ever" / "when was the first" → sort_by="oldest", limit=1

COMPOUND QUERIES — extract ALL dimensions mentioned:
- "resolved last night" → states=["resolved"] AND time_range="yesterday"
- "open P1 incidents from last week" → states=["new","in_progress"] AND priorities=[1] AND time_range="last_7d"
- "latest critical incidents" → priorities=[1] AND sort_by="newest"

COUNT/STATS QUERIES:
- "how many incidents" → intent=get_incident_stats
- "how many resolved" → intent=get_incident_stats, states=["resolved"]
- "count of open P1" → intent=get_incident_stats, states=["new","in_progress"], priorities=[1]

Only include entity fields the user actually mentioned. Leave others null.

─── SERVICENOW QUERY SYNTAX REFERENCE ───

You must generate a valid ServiceNow encoded query string in the sn_query field.
This query will be sent directly to the ServiceNow Table API.

FIELD NAMES (use these exact names):
- priority  (numeric: 1=Critical, 2=High, 3=Moderate, 4=Low, 5=Planning)
- state     (numeric: 1=New, 2=In Progress, 3=On Hold, 6=Resolved, 7=Closed)
- category  (string: e.g. "network", "software", "hardware", "inquiry", "database")
- opened_at    (datetime: format YYYY-MM-DD HH:MM:SS)
- resolved_at  (datetime: format YYYY-MM-DD HH:MM:SS)
- closed_at    (datetime: format YYYY-MM-DD HH:MM:SS)
- short_description (string: use LIKE for keyword search)
- number       (string: e.g. INC0010001)

REFERENCE FIELDS — these are person/group lookups and REQUIRE DOT-WALKING:
ServiceNow stores reference fields as sys_ids internally. To query by
display name you MUST use dot-walking with ".name":
- assigned_to.name    (person name: use LIKE)   assigned_to.nameLIKECharlie
- caller_id.name      (caller name: use LIKE)   caller_id.nameLIKEFred Luddy
- assignment_group.name (group name: use LIKE)   assignment_group.nameLIKENetwork
NEVER query these fields without ".name" — e.g. caller_id=Fred Luddy WILL NOT WORK.

OPERATORS:
- =    exact match          priority=1
- !=   not equal            state!=7
- LIKE contains substring   short_descriptionLIKElogin error
- >=   greater or equal     opened_at>=2025-01-01 00:00:00
- <=   less or equal        opened_at<=2025-12-31 23:59:59
- >    greater than
- <    less than
- IN   value in list        stateIN1,2

CONNECTORS:
- ^    AND                  priority=1^state=1
- ^OR  OR                   priority=1^ORpriority=2
- ^NQ  new query (OR block) short_descriptionLIKEfoo^NQdescriptionLIKEfoo

SORTING (set in sn_orderby field, NOT in sn_query):
- ORDERBYopened_at          ascending by opened date
- ORDERBYDESCopened_at      descending by opened date (newest first) — DEFAULT
- ORDERBYpriority           ascending by priority (P1 first)
- ORDERBYDESCpriority       descending by priority (P5 first)
- ORDERBYDESCresolved_at    most recently resolved first

DATE HANDLING IN QUERIES:
- Today:        opened_at>=YYYY-MM-DD 00:00:00       (use today's date)
- Yesterday:    opened_at>=YYYY-MM-DD 00:00:00^opened_at<YYYY-MM-DD 00:00:00  (yesterday start to today start)
- Last 7 days:  opened_at>=YYYY-MM-DD 00:00:00       (7 days ago date)
- Last 30 days: opened_at>=YYYY-MM-DD 00:00:00       (30 days ago date)
- Year 2025:    opened_at>=2025-01-01 00:00:00^opened_at<=2025-12-31 23:59:59
- All time:     do NOT add any opened_at filter

EXAMPLES:
- "resolved P1 incidents from last week"
  sn_query: "priority=1^state=6^opened_at>=2025-02-16 00:00:00"
  sn_orderby: "ORDERBYDESCopened_at"

- "show all open incidents"
  sn_query: "stateIN1,2"
  sn_orderby: "ORDERBYDESCopened_at"

- "incidents about login error"
  sn_query: "short_descriptionLIKElogin error"
  sn_orderby: "ORDERBYDESCopened_at"

- "how many incidents have been resolved"
  sn_query: "state=6"
  sn_orderby: "ORDERBYDESCopened_at"

- "how many incidents have been resolved so far"
  sn_query: "state=6"
  sn_orderby: "ORDERBYDESCopened_at"

- "how many incidents are there in total"
  sn_query: ""
  sn_orderby: "ORDERBYDESCopened_at"

- "when was the first incident created"
  sn_query: ""
  sn_orderby: "ORDERBYopened_at"

- "show me all incidents" (no filters)
  sn_query: ""
  sn_orderby: "ORDERBYDESCopened_at"

- "incidents assigned to Charlie Whitherspoon"
  sn_query: "assigned_to.nameLIKECharlie Whitherspoon"
  sn_orderby: "ORDERBYDESCopened_at"

- "incidents called by Fred Luddy" / "incidents from caller Fred Luddy"
  sn_query: "caller_id.nameLIKEFred Luddy"
  sn_orderby: "ORDERBYDESCopened_at"

- "incidents from Networks assignment group"
  sn_query: "assignment_group.nameLIKENetwork"
  sn_orderby: "ORDERBYDESCopened_at"

─── ACTIVE FILTERS FROM PRIOR TURNS ───
If active_filters is not empty, the user is refining a previous query.
You MUST incorporate all active filters into sn_query alongside any new
filters from the current message. If the user explicitly contradicts a
prior filter, the new value replaces the old one.

Today's date is: {today}

Return valid JSON matching the schema."""),
    ("human", """Conversation history:
{history}

Active filters from prior turns: {active_filters}

Current message: {question}"""),
])


# ── Confirmation / cancellation fast-path tokens ─────────────────────

_CONFIRM_TOKENS = {"yes", "confirm", "go ahead", "do it", "proceed", "ok", "sure", "yep", "yeah", "approve"}
_CANCEL_TOKENS = {"no", "cancel", "never mind", "nevermind", "stop", "abort", "don't", "nope", "back"}


def _is_action_response(text: str) -> str | None:
    """Return 'confirm', 'cancel', or None based on the user's message."""
    lower = text.strip().lower().rstrip(".!?")
    if lower in _CONFIRM_TOKENS:
        return "confirm"
    if lower in _CANCEL_TOKENS:
        return "cancel"
    return None


# ── Node ─────────────────────────────────────────────────────────────

def sn_classify_node(state):
    """Layer 1: Classify intent + extract entities + generate SN query via LLM."""
    question = state["question"]
    session = dict(state.get("sn_session") or {})

    # ── Fast-path: pending action confirmation/cancellation ───────
    pending = session.get("pending_action")
    if pending:
        response_type = _is_action_response(question)
        if response_type == "confirm":
            session["sn_intent"] = pending["type"]
            session["action_confirmed"] = True
            session["_turn_entities"] = {}
            return {
                "sn_session": session,
                "steps": ["sn_classify:action_confirmed"],
            }
        if response_type == "cancel":
            session.pop("pending_action", None)
            session["awaiting"] = None
            session["action_confirmed"] = False
            session["sn_intent"] = "fetch_incidents"
            session["_turn_entities"] = {}
            return {
                "generation": "Action cancelled.",
                "sn_session": session,
                "steps": ["sn_classify:action_cancelled"],
            }

    # ── Normal LLM classification path ───────────────────────────
    history = state.get("conversation_history", [])

    history_text = "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in history[-8:]
    ) or "(none)"

    accumulated = session.get("accumulated_entities", {})
    active_filters = json.dumps(accumulated) if accumulated else "(none)"

    from datetime import date
    today = date.today().isoformat()

    llm = get_llm()
    chain = CLASSIFY_PROMPT | llm.with_structured_output(SNClassification)

    result: SNClassification = chain.invoke({
        "question": question,
        "history": history_text,
        "active_filters": active_filters,
        "today": today,
    })

    extracted = {}
    if result.incident_id:
        extracted["incident_id"] = result.incident_id
    if result.priorities:
        extracted["priorities"] = result.priorities
    if result.states:
        extracted["states"] = result.states
    if result.time_range:
        extracted["time_range"] = result.time_range
    if result.category:
        extracted["category"] = result.category
    if result.assignee:
        extracted["assignee"] = result.assignee
    if result.keywords:
        extracted["keywords"] = result.keywords
    if result.sort_by:
        extracted["sort_by"] = result.sort_by
    if result.limit is not None:
        extracted["limit"] = result.limit

    session["sn_intent"] = result.intent
    session["_turn_entities"] = extracted
    session["sn_query"] = result.sn_query or ""
    session["sn_orderby"] = result.sn_orderby or "ORDERBYDESCopened_at"

    return {
        "sn_session": session,
        "steps": [
            f"sn_classify:intent={result.intent}",
            f"sn_classify:entities={list(extracted.keys())}",
            f"sn_classify:sn_query={result.sn_query or '(empty)'}",
        ],
    }
