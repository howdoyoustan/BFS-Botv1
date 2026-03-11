from resources.llm import get_llm
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

SYSTEM_PROMPT = """
You are an SOP assistant.

Rules:
- Answer using the provided SOP context. Extract and synthesize relevant steps, procedures, or guidance.
- If the context contains related information (e.g., platform restoration, recovery actions, triage steps, routing) that addresses the user's topic, present it clearly. The user may phrase their question differently than the SOP; look for semantic overlap.
- Use bullet points when presenting steps.
- Do NOT invent steps or actions not present in the context.
- Only respond with "I don't know - no SOP exists for this procedure." if the context is completely unrelated to the question (e.g., different domain, no overlapping concepts).
"""


def sop_generate_node(state):
    docs = state.get("documents", [])

    if not docs:
        return {
            "generation": "I don't know – no SOP exists for this procedure.",
            "steps": ["sop_generate:no_docs"],
        }

    context = "\n\n".join(d.page_content for d in docs)
    question = state["question"]

    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", "SOP Context:\n{context}\n\nQuestion:\n{question}"),
    ])

    llm = get_llm()
    chain = prompt | llm | StrOutputParser()

    answer = chain.invoke({"context": context, "question": question})

    # Debug: surface what was passed to the LLM (truncated for readability)
    ctx_preview = context[:400].replace("\n", " ") + ("..." if len(context) > 400 else "")
    steps = [
        "sop_generate",
        f"sop_ctx_preview: {ctx_preview}",
        f"sop_question: {question}",
    ]

    return {
        "generation": answer,
        "steps": steps,
    }
