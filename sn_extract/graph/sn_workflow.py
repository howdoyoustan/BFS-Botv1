"""
Minimal ServiceNow-only workflow.
Use this when you only need the SN chain (no SOP, GT, DE).
"""
from langgraph.graph import StateGraph, START, END
from graph.state import GraphState
from graph.intent.router import intent_router_node
from graph.nodes.sn.classify import sn_classify_node
from graph.nodes.sn.accumulator import sn_accumulate_node
from graph.nodes.sn.specificity import sn_score_node
from graph.nodes.sn.disambiguate import sn_disambiguate_node
from graph.nodes.sn.retrieve import sn_retrieve_node
from graph.nodes.sn.generate import sn_generate_node
from graph.nodes.sn.confirm import sn_confirm_node
from graph.nodes.sn.execute_action import sn_execute_action_node


def build_sn_workflow():
    """Build a workflow with only the ServiceNow chain."""
    workflow = StateGraph(GraphState)

    workflow.add_node("intent_router", intent_router_node)
    workflow.add_node("sn_classify", sn_classify_node)
    workflow.add_node("sn_accumulate", sn_accumulate_node)
    workflow.add_node("sn_score", sn_score_node)
    workflow.add_node("sn_disambiguate", sn_disambiguate_node)
    workflow.add_node("sn_retrieve", sn_retrieve_node)
    workflow.add_node("sn_generate", sn_generate_node)
    workflow.add_node("sn_confirm", sn_confirm_node)
    workflow.add_node("sn_execute_action", sn_execute_action_node)

    workflow.add_edge(START, "intent_router")
    # SN-only: route all intents to SN chain (override other chains)
    workflow.add_conditional_edges(
        "intent_router",
        lambda state: state["intent"],
        {
            "SERVICENOW_INCIDENT": "sn_classify",
            "AMBIGUOUS": "sn_classify",
            "SOP_QUERY": "sn_classify",
            "TROUBLESHOOTING": "sn_classify",
            "DATA_ENGINEERING": "sn_classify",
        },
    )
    workflow.add_edge("sn_classify", "sn_accumulate")
    workflow.add_edge("sn_accumulate", "sn_score")
    workflow.add_conditional_edges(
        "sn_score",
        lambda state: (state.get("sn_session") or {}).get("sn_action", "execute"),
        {
            "disambiguate": "sn_disambiguate",
            "execute": "sn_retrieve",
            "force_execute": "sn_retrieve",
            "confirm_action": "sn_confirm",
            "execute_action": "sn_execute_action",
        },
    )
    workflow.add_edge("sn_disambiguate", END)
    workflow.add_edge("sn_retrieve", "sn_generate")
    workflow.add_edge("sn_generate", END)
    workflow.add_edge("sn_confirm", END)
    workflow.add_edge("sn_execute_action", END)

    return workflow.compile()
