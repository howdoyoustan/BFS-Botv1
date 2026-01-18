from typing import TypedDict, List, Annotated
import operator
from langchain_core.documents import Document

class GraphState(TypedDict):
    question: str
    intent: str

    documents: Annotated[List[Document], operator.add]
    generation: str

    is_relevant: str
    is_grounded: str

    gt_used_llm_fallback: bool
    retry_generation_count: int
    kb_retry_count: int
    kb_enriched: bool

    steps: Annotated[List[str], operator.add]
