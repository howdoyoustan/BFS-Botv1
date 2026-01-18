from resources.vectorstore import get_vectorstore
def sop_retrieve_node(state):
    vectorstore = get_vectorstore(collection_name="sop_knowledge")

    if vectorstore is None:
        # SOP KB not configured yet
        return {
            "documents": [],
            "steps": ["sop_retrieve:no_vectorstore"]
        }

    question = state["question"]

    docs = vectorstore.similarity_search(question, k=5)

    return {
        "documents": docs,
        "steps": ["sop_retrieve"]
    }
