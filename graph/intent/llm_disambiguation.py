from langchain_core.prompts import ChatPromptTemplate
from resources.llm import get_llm
from graph.intent.schema import IntentResolution

INTENT_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are an intent classifier for a data platform assistant.\n\n"
        "Choose EXACTLY ONE intent:\n"
        "- SOP_QUERY (procedures, onboarding, runbooks)\n"
        "- TROUBLESHOOTING (generic system or OS issues)\n"
        "- DATA_ENGINEERING (Spark, Airflow, pipelines, schemas)\n\n"
        "Return ONLY the intent label."
    ),
    ("human", "{question}")
])

def llm_intent_disambiguation_node(state):
    llm = get_llm().with_structured_output(IntentResolution)

    result = llm.invoke(
        INTENT_PROMPT.format_messages(
            question=state["question"]
        )
    )

    intent = result.intent

    if intent not in {
        "SOP_QUERY",
        "TROUBLESHOOTING",
        "DATA_ENGINEERING",
    }:
        raise ValueError(f"LLM returned invalid intent: {intent}")

    return {
        "intent": intent,
        "steps": [f"intent:LLM_DISAMBIGUATED:{intent}"]
    }
