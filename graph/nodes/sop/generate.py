from resources.llm import get_llm
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

SYSTEM_PROMPT = """
You are an SOP assistant.

Rules:
- Answer ONLY using the provided SOP context.
- If the SOP does not contain the answer, respond EXACTLY with:
  "I don't know - no SOP exists for this procedure."
- Do NOT add steps.
- Do NOT infer missing actions.
- Use bullet points if steps exist.
"""

def sop_generate_node(state):
    docs = state.get("documents", [])

    if not docs:
        return {
            "generation": "I don't know – no SOP exists for this procedure.",
            "steps": ["sop_generate:no_docs"]
        }

    context = "\n\n".join(d.page_content for d in docs)

    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", "SOP Context:\n{context}\n\nQuestion:\n{question}")
    ])

    llm = get_llm()
    chain = prompt | llm | StrOutputParser()

    answer = chain.invoke({
        "context": context,
        "question": state["question"]
    })

    return {
        "generation": answer,
        "steps": ["sop_generate"]
    }
