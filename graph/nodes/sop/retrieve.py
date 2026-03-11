from resources.vectorstore import get_vectorstore

# ChromaDB returns distance (lower = more similar). For cosine: 0=perfect, ~1=unrelated.
# Keep docs with distance below this; if all fail, we still pass top 3.
DISTANCE_THRESHOLD = 0.95


def sop_retrieve_node(state):
    vectorstore = get_vectorstore(collection_name="sop_knowledge")

    if vectorstore is None:
        return {
            "documents": [],
            "steps": ["sop_retrieve:no_vectorstore"],
        }

    question = state["question"]

    # Retrieve more candidates and filter by relevance score
    results = vectorstore.similarity_search_with_score(question, k=10)

    # Keep docs with distance below threshold; fallback to top 3 if all are weak
    docs = [doc for doc, score in results if score <= DISTANCE_THRESHOLD]
    if not docs:
        docs = [doc for doc, _ in results[:3]]

    steps = ["sop_retrieve"]
    if results:
        top_score = results[0][1]
        steps.append(f"sop_retrieve:top_score={top_score:.3f}, kept={len(docs)}")

    return {
        "documents": docs,
        "steps": steps,
    }
