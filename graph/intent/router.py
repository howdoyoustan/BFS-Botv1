from graph.intent.rules import classify_intent_rule_based
from resources.llm import get_llm
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel

class IntentResult(BaseModel):
    intent: str  # SOP_QUERY | TROUBLESHOOTING | DATA_ENGINEERING

def intent_router_node(state):
    # 1. Respect upstream intent (critical for testing)
    if "intent" in state and state["intent"] is not None:
        return {
            "intent": state["intent"],
            "steps": [f"intent:{state['intent']}"]
        }

    query = state["question"]
    intent = classify_intent_rule_based(query)

    return {
        "intent": intent,
        "steps": [f"intent:{intent}"]
    }

# INTENT_PROMPT = ChatPromptTemplate.from_messages([
#     ("system",
#      "Classify the user query into exactly one intent:\n"
#      "- SOP_QUERY\n"
#      "- TROUBLESHOOTING\n"
#      "- DATA_ENGINEERING\n\n"
#      "Return ONLY the intent label."),
#     ("human", "{query}")
# ])

##FIRST BROKEN IMPLEMENTATION
# def intent_router_node(state):
#     query = state["question"]

#     intent = classify_intent_rule_based(query)

#     if intent == "AMBIGUOUS":
#         llm = get_llm().with_structured_output(IntentResult)
#         result = llm.invoke(
#             INTENT_PROMPT.format_messages(query=query)
#         )
#         intent = result.intent

#     return {
#         "intent": intent,
#         "steps": [f"intent:{intent}"]
#     }

###SECOND IMPLEMENTATION
# def intent_router_node(state):
#     # 🔒 Respect upstream intent if explicitly provided
#     if "intent" in state and state["intent"] is not None:
#         return {
#             "intent": state["intent"],
#             "steps": [f"intent:{state['intent']}"]
#         }

#     # Otherwise classify
#     query = state["question"]
#     intent = classify_intent_rule_based(query)

#     if intent == "AMBIGUOUS":
#         # LLM fallback here later
#         pass

#     return {
#         "intent": intent,
#         "steps": [f"intent:{intent}"]
#     }
