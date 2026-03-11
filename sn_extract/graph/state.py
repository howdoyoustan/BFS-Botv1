from typing import TypedDict, List, Annotated, Optional
import operator
from langchain_core.documents import Document


class SNSession(TypedDict, total=False):
    """Full session state for the multi-turn ServiceNow conversation."""
    sn_intent: str                       # sub-intent: fetch_incidents, get_incident_detail, etc.
    accumulated_entities: dict           # merged filter entities across turns
    specificity_score: float             # latest weighted score (0.0 – 1.0)
    sn_action: str                       # routing decision: "disambiguate" | "execute" | "force_execute" | "confirm_action" | "execute_action"
    disambiguation_count: int            # how many clarification rounds so far
    awaiting: Optional[str]              # dimension we asked the user to clarify
    dimension_counts: Optional[dict]     # cached aggregation for disambiguation display
    query_string: str                    # ServiceNow encoded query built from entities
    orderby: str                         # sort field
    pending_action: Optional[dict]       # action awaiting confirmation: {"type": ..., "sys_id": ..., "changes": ..., "incident": ...}
    action_confirmed: bool               # True when user has confirmed the pending action


class GraphState(TypedDict):
    question: str
    intent: str

    conversation_history: List[dict]     # [{"role": "user"|"assistant", "content": "..."}]

    documents: Annotated[List[Document], operator.add]
    generation: str

    is_relevant: str
    is_grounded: str

    gt_used_llm_fallback: bool
    retry_generation_count: int
    kb_retry_count: int
    kb_enriched: bool

    sn_incidents: List[dict]
    sn_session: Optional[SNSession]
    sn_response: Optional[dict]           # structured UI envelope for app.py

    steps: Annotated[List[str], operator.add]
