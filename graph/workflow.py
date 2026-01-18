from langgraph.graph import StateGraph, START, END

from graph.state import GraphState

# Intent router
from graph.intent.router import intent_router_node
from graph.routers.intent_router import route_by_intent
from graph.intent.llm_disambiguation import llm_intent_disambiguation_node

# SOP nodes
from graph.nodes.sop.retrieve import sop_retrieve_node
from graph.nodes.sop.relevance import sop_relevance_node
from graph.nodes.sop.generate import sop_generate_node

# GT nodes
from graph.nodes.gt.retrieve import gt_retrieve_node
from graph.nodes.gt.relevance import gt_relevance_node
from graph.nodes.gt.generate import gt_generate_node
from graph.nodes.gt.sufficiency import gt_sufficiency_node
from graph.nodes.gt.external_search import gt_external_search_node
from graph.nodes.gt.validate import gt_validate_node
from graph.nodes.gt.store_tribal import gt_store_tribal_node
from graph.nodes.gt.post_sufficiency import gt_post_sufficiency_node
# DE nodes
from graph.nodes.de.context_router import de_context_router_node
from graph.nodes.de.retrieve import de_retrieve_node
from graph.nodes.de.relevance import de_relevance_node
from graph.nodes.de.generate import de_generate_node
from graph.nodes.de.hallucination import de_hallucination_node
from graph.nodes.de.retry_generate import de_retry_generate_node
from graph.nodes.de.improve_kb import de_improve_kb_node

# DE routers
from graph.routers.de_router import de_decide_next_step


def build_workflow():
    workflow = StateGraph(GraphState)

    # -------------------------------------------------
    # Add nodes
    # -------------------------------------------------

    workflow.add_node("intent_router", intent_router_node)
    workflow.add_node("intent_llm_disambiguation",llm_intent_disambiguation_node)

    # SOP
    workflow.add_node("sop_retrieve", sop_retrieve_node)
    workflow.add_node("sop_relevance", sop_relevance_node)
    workflow.add_node("sop_generate", sop_generate_node)

    # GT
    workflow.add_node("gt_retrieve", gt_retrieve_node)
    workflow.add_node("gt_relevance", gt_relevance_node)
    workflow.add_node("gt_generate", gt_generate_node)
    workflow.add_node("gt_external_search", gt_external_search_node)
    workflow.add_node("gt_validate", gt_validate_node)
    workflow.add_node("gt_store_tribal", gt_store_tribal_node)
    workflow.add_node("gt_post_sufficiency", gt_post_sufficiency_node)

    # DE
    workflow.add_node("de_context_router", de_context_router_node)
    workflow.add_node("de_retrieve", de_retrieve_node)
    workflow.add_node("de_relevance", de_relevance_node)
    workflow.add_node("de_generate", de_generate_node)
    workflow.add_node("de_hallucination", de_hallucination_node)
    workflow.add_node("de_retry_generate", de_retry_generate_node)
    workflow.add_node("de_improve_kb", de_improve_kb_node)

    # -------------------------------------------------
    # Entry
    # -------------------------------------------------

    workflow.add_edge(START, "intent_router")

    # -------------------------------------------------
    # Intent-based routing
    # -------------------------------------------------

    workflow.add_conditional_edges(
    "intent_router",
    lambda state: state["intent"],
    {
        "SOP_QUERY": "sop_retrieve",
        "DATA_ENGINEERING": "de_context_router",
        "TROUBLESHOOTING": "gt_retrieve",
        "AMBIGUOUS": "intent_llm_disambiguation",
    },
)

    workflow.add_conditional_edges(
    "intent_llm_disambiguation",
    lambda state: state["intent"],
    {
        "SOP_QUERY": "sop_retrieve",
        "DATA_ENGINEERING": "de_context_router",
        "TROUBLESHOOTING": "gt_retrieve",
    },
)


    # -------------------------------------------------
    # SOP CHAIN (read-only)
    # -------------------------------------------------

    workflow.add_edge("sop_retrieve", "sop_relevance")
    workflow.add_edge("sop_relevance", "sop_generate")
    workflow.add_edge("sop_generate", END)

    # -------------------------------------------------
    # GT CHAIN (generic troubleshooting)
    # -------------------------------------------------

    # Step 1: retrieve → relevance
    workflow.add_edge("gt_retrieve", "gt_relevance")

    # Step 2: relevance decision
    workflow.add_conditional_edges(
        "gt_relevance",
        lambda state: (
            "relevant" if state.get("is_relevant") == "yes" else "not_relevant"
        ),
        {
            "relevant": "gt_generate",          # KB-based answer
            "not_relevant": "gt_external_search" # escalate
        },
    )

    # Step 3: external search → generate (LLM fallback)
    workflow.add_edge("gt_external_search", "gt_generate")

    # Step 4: ALWAYS check sufficiency after generate
    workflow.add_conditional_edges(
        "gt_generate",
        gt_sufficiency_node,
        {
            "sufficient": "gt_post_sufficiency",
            "insufficient": END,
        },
    )

    # Step 5: post-sufficiency decision (learn or not)
    workflow.add_conditional_edges(
        "gt_post_sufficiency",
        lambda state: (
            "validate"
            if state.get("gt_used_llm_fallback")
            else "finalize"
        ),
        {
            "validate": "gt_validate",
            "finalize": END,
        },
    )

    # Step 6: validation gate
    workflow.add_conditional_edges(
        "gt_validate",
        lambda state: "store" if state.get("kb_enriched") else "finalize",
        {
            "store": "gt_store_tribal",
            "finalize": END,
        },
    )

    workflow.add_edge("gt_store_tribal", END)


    # -------------------------------------------------
    # DE CHAIN (strict, evidence-based)
    # -------------------------------------------------

    # DE linear flow
    workflow.add_edge("de_context_router", "de_retrieve")
    workflow.add_edge("de_retrieve", "de_relevance")
    workflow.add_edge("de_relevance", "de_generate")
    workflow.add_edge("de_generate", "de_hallucination")

    # Decision point
    workflow.add_conditional_edges(
        "de_hallucination",
        de_decide_next_step,
        {
            "retry_generate": "de_retry_generate",
            "improve_kb": "de_improve_kb",
            "finalize": END,
        },
    )

    # Retry generation loop
    workflow.add_edge("de_retry_generate", "de_generate")

    # Improve KB loop
    workflow.add_edge("de_improve_kb", "de_retrieve")

    # -------------------------------------------------
    return workflow.compile()
