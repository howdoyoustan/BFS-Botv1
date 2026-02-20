import streamlit as st
import tempfile
import os
from dotenv import load_dotenv

load_dotenv(override=True)

from graph.workflow import build_workflow
from resources.vectorstore import get_vectorstore
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

# ── Page config ──────────────────────────────────────────────────────

st.set_page_config(
    page_title="BFS Bot v2",
    page_icon=":wrench:",
    layout="wide",
)

# ── Session state ────────────────────────────────────────────────────

if "messages" not in st.session_state:
    st.session_state.messages = []
if "sop_chunk_count" not in st.session_state:
    st.session_state.sop_chunk_count = 0

# ── Build graph (cached) ────────────────────────────────────────────

@st.cache_resource
def get_app():
    return build_workflow()

app = get_app()

INTENT_OPTIONS = {
    "Auto-detect (Intent Router)": None,
    "SOP Query": "SOP_QUERY",
    "Data Engineering": "DATA_ENGINEERING",
    "Troubleshooting": "TROUBLESHOOTING",
    "ServiceNow Incident": "SERVICENOW_INCIDENT",
}

INTENT_COLORS = {
    "SOP_QUERY": "blue",
    "DATA_ENGINEERING": "orange",
    "TROUBLESHOOTING": "red",
    "SERVICENOW_INCIDENT": "green",
    "AMBIGUOUS": "gray",
}

INTENT_LABELS = {
    "SOP_QUERY": ":blue[SOP]",
    "DATA_ENGINEERING": ":orange[DATA ENGINEERING]",
    "TROUBLESHOOTING": ":red[TROUBLESHOOTING]",
    "SERVICENOW_INCIDENT": ":green[SERVICENOW]",
    "AMBIGUOUS": ":gray[AMBIGUOUS]",
}

# ── Sidebar ──────────────────────────────────────────────────────────

with st.sidebar:
    st.title("BFS Bot v2")
    st.caption("Cross-Functional Incident Triage")

    st.divider()

    # Intent selector
    st.subheader("Intent Override")
    selected_label = st.selectbox(
        "Choose an intent or let the router decide",
        options=list(INTENT_OPTIONS.keys()),
        index=0,
        label_visibility="collapsed",
    )
    intent_override = INTENT_OPTIONS[selected_label]

    if intent_override:
        st.info(f"Forcing intent: **{intent_override}**")
    else:
        st.caption("The intent router will classify your query automatically.")

    st.divider()

    # SOP upload
    st.subheader("SOP Knowledge Base")

    uploaded_file = st.file_uploader(
        "Upload an SOP document (PDF)",
        type=["pdf"],
        key="sop_uploader",
    )

    if uploaded_file is not None:
        if st.button("Seed into Knowledge Base", type="primary", use_container_width=True):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(uploaded_file.read())
                tmp_path = tmp.name

            with st.spinner("Processing PDF..."):
                try:
                    loader = PyPDFLoader(tmp_path)
                    pages = loader.load()

                    splitter = RecursiveCharacterTextSplitter(
                        chunk_size=800,
                        chunk_overlap=150,
                    )
                    chunks = splitter.split_documents(pages)

                    sop_docs = [
                        Document(
                            page_content=chunk.page_content,
                            metadata={
                                "type": "SOP",
                                "source": "pdf",
                                "filename": uploaded_file.name,
                                "topic": uploaded_file.name.replace(".pdf", ""),
                                "owner": "data-platform",
                                "version": "1.0",
                                "page": chunk.metadata.get("page"),
                            },
                        )
                        for chunk in chunks
                    ]

                    vectorstore = get_vectorstore("sop_knowledge")
                    vectorstore.add_documents(sop_docs)

                    st.session_state.sop_chunk_count += len(sop_docs)
                    st.success(f"Seeded {len(sop_docs)} chunks from **{uploaded_file.name}**")
                except Exception as e:
                    st.error(f"Failed to process PDF: {e}")
                finally:
                    os.unlink(tmp_path)

    if st.session_state.sop_chunk_count > 0:
        st.metric("SOP Chunks Loaded", st.session_state.sop_chunk_count)

    st.divider()

    # Chain legend
    st.subheader("Chains")
    st.markdown(
        """
        | Chain | Status |
        |---|---|
        | **SOP** | Working (needs SOP docs) |
        | **SN** | Live (ServiceNow API) |
        | **DE** | Stub (placeholder) |
        | **GT** | Stub (placeholder) |
        """
    )

    if st.button("Clear Chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()


# ── Main chat area ───────────────────────────────────────────────────

st.header("Incident Triage Assistant")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant":
            intent = msg.get("intent", "")
            label = INTENT_LABELS.get(intent, f":gray[{intent}]")
            st.caption(f"Chain: {label}")
        st.markdown(msg["content"])
        if "steps" in msg and msg["steps"]:
            with st.expander("Graph Trace"):
                for i, step in enumerate(msg["steps"], 1):
                    st.text(f"  {i}. {step}")


# ── Handle user input ────────────────────────────────────────────────

if prompt := st.chat_input("Ask a question..."):
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        state = {
            "question": prompt,
            "documents": [],
            "steps": [],
            "retry_generation_count": 0,
            "kb_retry_count": 0,
            "kb_enriched": True,
        }
        if intent_override is not None:
            state["intent"] = intent_override

        with st.spinner("Running graph..."):
            try:
                result = app.invoke(state)
            except Exception as e:
                result = {
                    "generation": f"**Error:** {e}",
                    "steps": ["error"],
                    "intent": intent_override or "unknown",
                }

        generation = result.get("generation", "No response generated.")
        steps = result.get("steps", [])
        intent_used = result.get("intent", "unknown")

        label = INTENT_LABELS.get(intent_used, f":gray[{intent_used}]")
        st.caption(f"Chain: {label}")
        st.markdown(generation)

        if steps:
            with st.expander("Graph Trace"):
                for i, step in enumerate(steps, 1):
                    st.text(f"  {i}. {step}")

        st.session_state.messages.append({
            "role": "assistant",
            "content": generation,
            "steps": steps,
            "intent": intent_used,
        })
