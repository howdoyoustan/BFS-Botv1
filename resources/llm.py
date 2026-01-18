from langchain_openai import ChatOpenAI

def get_llm(
    temperature: float = 0.0,
    model: str = "gpt-4o",
):
    """
    Central LLM factory.
    All nodes MUST use this.
    """
    return ChatOpenAI(
        model=model,
        temperature=temperature,
    )
