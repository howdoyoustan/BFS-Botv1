from langchain_core.documents import Document
from tools.write_to_vector_db import write_to_vector_db
from resources.vectorstore import get_vectorstore

vectorstore = get_vectorstore(collection_name="tribal_knowledge")

def gt_store_tribal_node(state):
    """
    Stores validated tribal knowledge as heuristics.
    """

    content = state["generation"]

    doc = Document(
        page_content=content,
        metadata={
            "domain": "generic_troubleshooting",
            "confidence": "heuristic",
            "verified": False,
            "source": "llm_validated"
        }
    )

    stored_chunks = write_to_vector_db(
        docs=[doc],
        vectorstore=vectorstore
    )

    return {
        "kb_enriched": stored_chunks > 0,
        "steps": [f"gt_store_tribal:{stored_chunks}"]
    }
