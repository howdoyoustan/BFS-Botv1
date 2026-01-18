from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
import os

CHROMA_BASE_DIR = os.path.join(os.getcwd(), "chroma")

def get_vectorstore(collection_name: str):
    embeddings = OpenAIEmbeddings()

    return Chroma(
        collection_name=collection_name,
        persist_directory=CHROMA_BASE_DIR,
        embedding_function=embeddings,
    )
