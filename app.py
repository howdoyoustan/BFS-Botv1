import streamlit as st
import pandas as pd
import tempfile
import os
import re
from dotenv import load_dotenv

load_dotenv(override=True)

from graph.workflow import build_workflow
from resources.vectorstore import get_vectorstore
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from mcp.servicenow import ServiceNowClient

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
if "sn_session" not in st.session_state:
    st.session_state.sn_session = None
if "sn_ui_phase" not in st.session_state:
    st.session_state.sn_ui_phase = None      # None | "showing_filters" | "showing_list" | "showing_detail"
if "_pending_synthetic" not in st.session_state:
    st.session_state._pending_synthetic = None


def queue_user_prompt(text: str, *, pending_payload: str | None = None):
    """Queue a synthetic user prompt and rerun the app."""
    st.session_state.messages.append({"role": "user", "content": text})
    st.session_state._pending_synthetic = pending_payload or text
    st.rerun()


def _get_current_incident_context() -> str | None:
    """Best-effort current incident number from session state or recent responses."""
    sn_sess = st.session_state.get("sn_session") or {}
    pending = sn_sess.get("pending_action") or {}

    if pending.get("incident_number"):
        return pending["incident_number"]

    snapshot = pending.get("incident_snapshot") or {}
    if snapshot.get("number"):
        return snapshot["number"]

    for msg in reversed(st.session_state.get("messages", [])):
        sn_resp = msg.get("sn_response") if isinstance(msg, dict) else None
        if not sn_resp:
            continue
        inc = sn_resp.get("incident") or {}
        if inc.get("number"):
            return inc["number"]

    return None


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

    st.subheader("Session Status")
    phase_labels = {
        None: "Idle",
        "showing_filters": "Filtering incidents",
        "showing_list": "Reviewing incident list",
        "showing_detail": "Viewing incident details",
        "awaiting_confirmation": "Waiting for action confirmation",
    }
    st.markdown(
        f"**Current SN phase:** {phase_labels.get(st.session_state.sn_ui_phase, 'Idle')}  \n"
        f"**Messages in chat:** {len(st.session_state.messages)}"
    )

    st.divider()

    st.subheader("Current Context")
    current_incident = _get_current_incident_context()
    sn_sess = st.session_state.get("sn_session") or {}
    pending_action = sn_sess.get("pending_action") or {}
    incident_text = current_incident or "_None selected yet_"
    pending_text = pending_action.get("type") or "_None_"
    awaiting_text = sn_sess.get("awaiting") or "_None_"
    st.markdown(
        f"**Incident:** {incident_text}  \n"
        f"**Pending action:** {pending_text}  \n"
        f"**Awaiting:** {awaiting_text}"
    )

    st.divider()

    st.subheader("SOP Knowledge Base")

    uploaded_file = st.file_uploader(
        "Upload an SOP document (PDF)",
        type=["pdf"],
        key="sop_uploader",
    )

    if uploaded_file is not None:
        if st.button("Seed into Knowledge Base", type="primary", width="stretch"):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(uploaded_file.read())
                tmp_path = tmp.name

            with st.spinner("Processing PDF..."):
                try:
                    loader = PyPDFLoader(tmp_path)
                    pages = loader.load()
                    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=150)
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

    if st.button("Clear Chat", width="stretch"):
        st.session_state.messages = []
        st.session_state.sn_session = None
        st.session_state.sn_ui_phase = None
        st.session_state._pending_synthetic = None
        st.rerun()


# ── Synthetic message injection ──────────────────────────────────────

def inject_selection(text: str):
    """Treat a widget click as if the user typed a message."""
    queue_user_prompt(text)


def inject_incident_lookup(inc_number: str):
    """Direct incident lookup — bypasses the full graph."""
    queue_user_prompt(
        f"Show details for {inc_number}",
        pending_payload=f"__direct_lookup__:{inc_number}",
    )


def inject_action(inc_number: str, action: str):
    """Trigger an incident action (e.g. acknowledge, resolve) — runs through the graph."""
    queue_user_prompt(f"{action} {inc_number}")


def _update_pending_resolve(notes: str, close_code: str | None = None):
    """Store user-provided closure notes and close code in the session's pending action."""
    sn_sess = st.session_state.get("sn_session") or {}
    pending = sn_sess.get("pending_action")
    if pending and "changes" in pending:
        pending["changes"]["close_notes"] = notes
        if close_code:
            pending["changes"]["close_code"] = close_code
        st.session_state.sn_session = sn_sess


def _update_pending_work_notes(notes: str):
    """Store user-provided work notes in the session's pending action."""
    sn_sess = st.session_state.get("sn_session") or {}
    pending = sn_sess.get("pending_action")
    if pending and "changes" in pending:
        pending["changes"]["work_notes"] = notes
        st.session_state.sn_session = sn_sess


def _update_pending_escalate(target_priority: str):
    """Store selected target priority in the session's pending action."""
    sn_sess = st.session_state.get("sn_session") or {}
    pending = sn_sess.get("pending_action")
    if pending:
        pending["target_priority"] = target_priority
        st.session_state.sn_session = sn_sess


# ── Helpers for ServiceNow reference/choice fields ─────────────────

def _format_ref_value(val):
    """Extract display string from ServiceNow reference/choice field (can be str or dict)."""
    if val is None:
        return "N/A"
    if isinstance(val, dict):
        return val.get("display_value", str(val))
    return str(val) if val else "N/A"


# ── Interactive SN response renderer ────────────────────────────────

def render_sn_response(response: dict, msg_idx: int):
    """Render a structured sn_response with interactive Streamlit widgets."""
    resp_type = response.get("type", "")

    if resp_type == "disambiguation":
        _render_disambiguation(response, msg_idx)
    elif resp_type == "incident_list":
        _render_incident_list(response, msg_idx)
    elif resp_type == "incident_stats":
        _render_incident_stats(response, msg_idx)
    elif resp_type == "single_incident":
        _render_single_incident(response, msg_idx)
    elif resp_type == "action_confirm":
        _render_action_confirm(response, msg_idx)
    elif resp_type == "action_result":
        _render_action_result(response, msg_idx)
    elif resp_type == "action_needs_input":
        st.info(response.get("text", ""))
    elif resp_type == "recovery":
        _render_recovery(response, msg_idx)
    else:
        st.markdown(response.get("text", ""))


def _render_disambiguation(response: dict, msg_idx: int):
    st.markdown(response.get("text", ""))

    filter_groups = response.get("filters", [])
    if not filter_groups:
        st.caption("Try broader filters or start over:")
        cols = st.columns(2)
        with cols[0]:
            if st.button("Try broader filters", key=f"refine_disambig_empty_{msg_idx}", width="stretch"):
                queue_user_prompt("Try broader filters", pending_payload="__refine_filters_all__")
        with cols[1]:
            if st.button("Start over", key=f"start_over_disambig_empty_{msg_idx}", width="stretch"):
                st.session_state.messages = []
                st.session_state.sn_session = None
                st.session_state.sn_ui_phase = None
                st.session_state._pending_synthetic = None
                st.rerun()
        return

    st.markdown("**To narrow this down, pick a filter:**")

    for grp in filter_groups:
        dim = grp["dimension"]
        dim_label = grp["dimension_label"]
        options = grp["options"]

        labels = [f"{o['label']} ({o['count']})" for o in options]
        key = f"pills_{dim}_{msg_idx}"

        selected = st.pills(f"{dim_label}:", labels, key=key)

        if selected:
            match_idx = labels.index(selected)
            raw_value = options[match_idx]["value"]
            dim_prefix, val = raw_value.split(":", 1)
            pri_match = re.search(r"\b([1-5])\b", val)
            pri_num = pri_match.group(1) if pri_match else val
            friendly = {
                "priority": f"show incidents with priority {pri_num}",
                "state": f"show incidents with state {val}",
                "time": f"incidents from {val.replace('_', ' ')}",
                "category": f"show incidents in category {val}",
                "assignee": f"show incidents assigned to assignment group {val}",
            }
            inject_selection(friendly.get(dim_prefix, val))

    cols = st.columns(2)
    with cols[0]:
        if st.button("Just show me all results", key=f"force_show_{msg_idx}", width="stretch"):
            inject_selection("just show me the results")
    with cols[1]:
        if st.button("Start over", key=f"start_over_{msg_idx}", width="stretch"):
            st.session_state.messages = []
            st.session_state.sn_session = None
            st.session_state.sn_ui_phase = None
            st.session_state._pending_synthetic = None
            st.rerun()


def _render_incident_list(response: dict, msg_idx: int):
    incidents = response.get("incidents", [])
    metrics = response.get("metrics", {})

    if not incidents:
        st.info("No incidents found matching your filters.")
        st.caption("Try different filters or start over:")
        ncols = st.columns(2)
        with ncols[0]:
            if st.button("Try different filters", key=f"refine_empty_{msg_idx}", width="stretch"):
                queue_user_prompt("Try different filters", pending_payload=f"__refine_filters__:{msg_idx}")
        with ncols[1]:
            if st.button("Start over", key=f"restart_empty_{msg_idx}", width="stretch"):
                st.session_state.messages = []
                st.session_state.sn_session = None
                st.session_state.sn_ui_phase = None
                st.session_state._pending_synthetic = None
                st.rerun()
        return

    st.markdown(response.get("text", ""))

    # Metrics row
    mcols = st.columns(4)
    mcols[0].metric("Total", metrics.get("total", len(incidents)))
    by_pri = metrics.get("by_priority", {})
    if by_pri:
        top_pri = next(iter(by_pri.items()), ("?", 0))
        mcols[1].metric("Top Priority", f"P{top_pri[0]}", f"{top_pri[1]} incidents")
    by_state = metrics.get("by_state", {})
    if by_state:
        top_state = next(iter(by_state.items()), ("?", 0))
        mcols[2].metric("Top State", top_state[0], f"{top_state[1]} incidents")
    if metrics.get("date_range"):
        mcols[3].metric("Date Range", metrics["date_range"])

    # Interactive table
    df = pd.DataFrame(incidents)
    display_cols = [c for c in ["number", "priority", "state", "opened_at", "short_description", "category"] if c in df.columns]
    if display_cols:
        st.dataframe(
            df[display_cols],
            width="stretch",
            hide_index=True,
            column_config={
                "number": st.column_config.TextColumn("Incident"),
                "priority": st.column_config.TextColumn("Priority"),
                "state": st.column_config.TextColumn("State"),
                "opened_at": st.column_config.TextColumn("Opened"),
                "short_description": st.column_config.TextColumn("Description"),
                "category": st.column_config.TextColumn("Category"),
            },
        )

    # Incident selector
    inc_numbers = [i["number"] for i in incidents if i.get("number")]
    if inc_numbers:
        selected = st.selectbox(
            "Select an incident for full details:",
            options=["-- Pick an incident --"] + inc_numbers,
            key=f"inc_select_{msg_idx}",
        )
        if selected and selected != "-- Pick an incident --":
            inject_incident_lookup(selected)

    # Recovery options
    st.caption("Not what you're looking for?")
    rcols = st.columns(3)
    with rcols[0]:
        if st.button("Refine filters", key=f"refine_{msg_idx}", width="stretch"):
            queue_user_prompt("Refine filters", pending_payload=f"__refine_filters__:{msg_idx}")
    with rcols[1]:
        if st.button("Not about incidents", key=f"not_inc_{msg_idx}", width="stretch"):
            st.session_state.sn_session = None
            st.session_state.sn_ui_phase = None
            st.rerun()
    with rcols[2]:
        if st.button("Start over", key=f"restart_{msg_idx}", width="stretch"):
            st.session_state.messages = []
            st.session_state.sn_session = None
            st.session_state.sn_ui_phase = None
            st.session_state._pending_synthetic = None
            st.rerun()


def _render_incident_stats(response: dict, msg_idx: int):
    """Render a count/stats-focused response."""
    st.markdown(response.get("text", ""))

    metrics = response.get("metrics", {})
    total = metrics.get("total", 0)

    mcols = st.columns(3)
    mcols[0].metric("Total Matching", total)
    by_pri = metrics.get("by_priority", {})
    if by_pri:
        top_pri = next(iter(by_pri.items()), ("?", 0))
        mcols[1].metric("Top Priority", f"P{top_pri[0]}", f"{top_pri[1]} in sample")
    by_state = metrics.get("by_state", {})
    if by_state:
        top_state = next(iter(by_state.items()), ("?", 0))
        mcols[2].metric("Top State", top_state[0], f"{top_state[1]} in sample")

    incidents = response.get("incidents", [])
    if incidents:
        st.caption(f"Sample of {len(incidents)} incidents:")
        df = pd.DataFrame(incidents)
        display_cols = [c for c in ["number", "priority", "state", "opened_at", "short_description"] if c in df.columns]
        if display_cols:
            st.dataframe(df[display_cols], width="stretch", hide_index=True)

        inc_numbers = [i["number"] for i in incidents if i.get("number")]
        if inc_numbers:
            selected = st.selectbox(
                "Select an incident for full details:",
                options=["-- Pick an incident --"] + inc_numbers,
                key=f"stats_sel_{msg_idx}",
            )
            if selected and selected != "-- Pick an incident --":
                inject_incident_lookup(selected)


def _render_single_incident(response: dict, msg_idx: int):
    inc = response.get("incident", {})
    if not inc:
        st.warning("Incident data not available.")
        return

    st.markdown(f"## Incident {inc.get('number', 'N/A')}")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Priority", _format_ref_value(inc.get("priority")))
    col2.metric("State", _format_ref_value(inc.get("state")))
    col3.metric("Impact", _format_ref_value(inc.get("impact")))
    col4.metric("Urgency", _format_ref_value(inc.get("urgency")))

    st.markdown(f"**Short Description:** {inc.get('short_description', 'N/A')}")
    st.markdown(f"**Category:** {_format_ref_value(inc.get('category'))}")
    st.markdown(f"**Assigned To:** {_format_ref_value(inc.get('assigned_to'))}")
    st.markdown(f"**Assignment Group:** {_format_ref_value(inc.get('assignment_group'))}")
    st.markdown(f"**Opened:** {inc.get('opened_at', 'N/A')}  |  **Resolved:** {inc.get('resolved_at', 'N/A')}")

    desc = inc.get("description", "") or "N/A"
    with st.expander("Description", expanded=True):
        st.text(desc)

    work_notes = inc.get("_work_notes_journal", [])
    if work_notes:
        with st.expander(f"Work Notes ({len(work_notes)})"):
            for note in work_notes:
                ts = note.get("sys_created_on", "")
                by = note.get("sys_created_by", "")
                val = note.get("value", "").strip()
                st.markdown(f"**{ts}** ({by}): {val}")

    close_notes = inc.get("close_notes", "")
    if close_notes:
        with st.expander("Close Notes"):
            st.text(close_notes)

    st.divider()
    st.markdown("**Actions**")
    inc_number = inc.get("number", "")
    if inc_number:
        acols = st.columns(3)
        with acols[0]:
            if st.button("Acknowledge", key=f"act_ack_{msg_idx}_{inc_number}", width="stretch"):
                inject_action(inc_number, "acknowledge")
            if st.button("Add Note", key=f"act_note_{msg_idx}_{inc_number}", width="stretch"):
                inject_action(inc_number, "add note")
        with acols[1]:
            if st.button("Resolve", key=f"act_resolve_{msg_idx}_{inc_number}", width="stretch"):
                inject_action(inc_number, "resolve")
            if st.button("Reassign", key=f"act_reassign_{msg_idx}_{inc_number}", width="stretch"):
                inject_action(inc_number, "reassign")
        with acols[2]:
            if st.button("Escalate", key=f"act_escalate_{msg_idx}_{inc_number}", width="stretch"):
                inject_action(inc_number, "escalate")
            if st.button("Link to Parent", key=f"act_link_{msg_idx}_{inc_number}", width="stretch"):
                inject_action(inc_number, "link")


def _render_action_confirm(response: dict, msg_idx: int):
    """Render a confirmation card for a pending ServiceNow action."""
    inc = response.get("incident", {})
    action_label = response.get("action_label", "Action")
    action_desc = response.get("action_description", "")
    changes = response.get("change_summary", [])
    requires_close_notes = response.get("requires_close_notes", False)
    requires_work_notes = response.get("requires_work_notes", False)
    requires_escalate_target = response.get("requires_escalate_target", False)
    action_type = response.get("action_type", "")

    st.markdown(f"### {action_label}")

    if requires_close_notes or requires_work_notes or requires_escalate_target:
        st.info("**Action wizard**\n1. Review incident + planned changes\n2. Fill in required details\n3. Confirm to execute")
    else:
        st.info("**Action wizard**\n1. Review incident + planned changes\n2. Confirm to execute")

    if inc:
        col1, col2, col3 = st.columns(3)
        col1.metric("Incident", inc.get("number", "N/A"))
        col2.metric("Current State", inc.get("state", "N/A"))
        col3.metric("Priority", inc.get("priority", "N/A"))

        st.markdown(f"**Description:** {inc.get('short_description', 'N/A')}")
        if inc.get("assigned_to"):
            st.markdown(f"**Currently Assigned To:** {_format_ref_value(inc['assigned_to'])}")
        if inc.get("assignment_group"):
            st.markdown(f"**Assignment Group:** {_format_ref_value(inc['assignment_group'])}")

    st.divider()
    st.markdown(action_desc)
    if changes:
        st.markdown("**Changes to be applied:**")
        for change in changes:
            st.markdown(f"- {change}")

    if requires_close_notes:
        st.divider()
        close_codes = response.get("close_codes", [])
        if close_codes:
            options = ["-- Select resolution code --"] + [c["label"] for c in close_codes]
            selected_label = st.selectbox(
                "Resolution code (required)",
                options=options,
                key=f"close_code_{msg_idx}",
            )
        st.text_area(
            "Resolution notes (required)",
            placeholder="Describe how the issue was resolved...",
            key=f"closure_notes_{msg_idx}",
            height=100,
        )
        if st.session_state.get("_confirm_error"):
            st.error(st.session_state["_confirm_error"])
            st.session_state["_confirm_error"] = None

    if requires_work_notes:
        st.divider()
        st.text_area(
            "Work note (required)",
            placeholder="Enter your note to add to the incident journal...",
            key=f"work_notes_{msg_idx}",
            height=100,
        )
        if st.session_state.get("_confirm_error"):
            st.error(st.session_state["_confirm_error"])
            st.session_state["_confirm_error"] = None

    escalate_options = [
        ("P1 - Critical", "1"),
        ("P2 - High", "2"),
        ("P3 - Moderate", "3"),
        ("P4 - Low", "4"),
        ("P5 - Planning", "5"),
    ]
    if requires_escalate_target:
        st.divider()
        selected = st.selectbox(
            "Target priority (escalate to higher = lower number)",
            options=["-- Select target priority --"] + [o[0] for o in escalate_options],
            key=f"escalate_target_{msg_idx}",
        )
        if st.session_state.get("_confirm_error"):
            st.error(st.session_state["_confirm_error"])
            st.session_state["_confirm_error"] = None

    st.divider()
    cols = st.columns(2)
    with cols[0]:
        if st.button(
            "Confirm",
            key=f"confirm_action_{msg_idx}",
            type="primary",
            width="stretch",
        ):
            if requires_close_notes:
                notes = (st.session_state.get(f"closure_notes_{msg_idx}", "") or "").strip()
                close_codes = response.get("close_codes", [])
                selected_label = st.session_state.get(f"close_code_{msg_idx}", "-- Select resolution code --") if close_codes else None

                if not notes:
                    st.session_state["_confirm_error"] = "Please provide resolution notes before confirming."
                    st.rerun()
                elif close_codes and (not selected_label or selected_label == "-- Select resolution code --"):
                    st.session_state["_confirm_error"] = "Please select a resolution code before confirming."
                    st.rerun()
                else:
                    close_code_val = None
                    if close_codes and selected_label and selected_label != "-- Select resolution code --":
                        for c in close_codes:
                            if c["label"] == selected_label:
                                close_code_val = c["value"]
                                break
                    _update_pending_resolve(notes, close_code_val)
                    inject_selection("confirm")
            elif requires_work_notes:
                notes = (st.session_state.get(f"work_notes_{msg_idx}", "") or "").strip()
                if not notes:
                    st.session_state["_confirm_error"] = "Please provide work notes before confirming."
                    st.rerun()
                else:
                    _update_pending_work_notes(notes)
                    inject_selection("confirm")
            elif requires_escalate_target:
                selected = st.session_state.get(f"escalate_target_{msg_idx}", "-- Select target priority --")
                if not selected or selected == "-- Select target priority --":
                    st.session_state["_confirm_error"] = "Please select a target priority before confirming."
                    st.rerun()
                else:
                    target_val = next((v for lbl, v in escalate_options if lbl == selected), None)
                    if target_val:
                        _update_pending_escalate(target_val)
                        inject_selection("confirm")
                    else:
                        inject_selection("confirm")
            else:
                inject_selection("confirm")
    with cols[1]:
        if st.button(
            "Cancel",
            key=f"cancel_action_{msg_idx}",
            width="stretch",
        ):
            queue_user_prompt("Cancel", pending_payload="__cancel_sn_action__")


def _render_action_result(response: dict, msg_idx: int):
    """Render the result of an executed ServiceNow action."""
    success = response.get("success", False)
    inc = response.get("incident", {})

    if success:
        st.success(response.get("text", "Action completed successfully."))
        if inc:
            col1, col2, col3 = st.columns(3)
            col1.metric("Incident", _format_ref_value(inc.get("number")))
            col2.metric("New State", _format_ref_value(inc.get("state")))
            col3.metric("Priority", _format_ref_value(inc.get("priority")))
            if inc.get("short_description"):
                st.markdown(f"**Description:** {inc['short_description']}")

        # Post-action options (same layout as "Not what you're looking for?")
        st.divider()
        st.caption("What would you like to do next?")
        inc_number = inc.get("number", "")
        pcols = st.columns(3)
        with pcols[0]:
            if st.button("Show other open incidents", key=f"post_show_{msg_idx}", width="stretch"):
                inject_selection("show open incidents")
        with pcols[1]:
            if st.button("View full details", key=f"post_view_{msg_idx}_{inc_number}", width="stretch"):
                if inc_number:
                    inject_incident_lookup(inc_number)
        with pcols[2]:
            if st.button("Start fresh", key=f"post_fresh_{msg_idx}", width="stretch"):
                st.session_state.messages = []
                st.session_state.sn_session = None
                st.session_state.sn_ui_phase = None
                st.session_state._pending_synthetic = None
                st.rerun()
    else:
        st.error(response.get("text", "Action failed."))


def _render_recovery(response: dict, msg_idx: int):
    st.markdown(response.get("text", "It looks like you might have changed direction."))
    options = response.get("recovery_options", [])
    if options:
        selected = st.pills("What would you like to do?", options, key=f"recovery_{msg_idx}")
        if selected:
            if "start over" in selected.lower():
                st.session_state.sn_session = None
                st.session_state.sn_ui_phase = None
                st.rerun()
            elif "back" in selected.lower() or "mistake" in selected.lower():
                st.rerun()
            else:
                inject_selection(selected)


# ── Direct incident lookup (bypasses graph) ──────────────────────────

def do_direct_lookup(inc_number: str):
    """Fetch a single incident directly from ServiceNow and render it."""
    try:
        client = ServiceNowClient()
        inc = client.get_incident(inc_number)
        if inc:
            work_notes = client.get_work_notes(inc["sys_id"])
            inc["_work_notes_journal"] = work_notes
            sn_response = {"type": "single_incident", "incident": inc, "text": f"Incident {inc_number}"}
            return sn_response
        else:
            return {"type": "single_incident", "incident": {}, "text": f"Incident {inc_number} not found."}
    except Exception as e:
        return {"type": "single_incident", "incident": {}, "text": f"Error looking up {inc_number}: {e}"}


# ── Main chat area ───────────────────────────────────────────────────

st.header("Incident Triage Assistant")

if not st.session_state.messages:
    with st.container(border=True):
        st.markdown("### 👋 Start here")
        st.caption("Pick a starter prompt or type your own question below.")

        starter_prompts = [
            "Show me open P1 and P2 incidents",
            "Show details for INC0010699",
            "Find incidents assigned to assignment group Data Engineering",
            "Find incidents assigned to John Smith",
            "Find incidents in category Network",
            "Find incidents in subcategory VPN",
            "Find incidents from caller Fred Luddy",
            "Find incidents assigned to Data Engineering in category Network",
            "Add a work note to INC0010699",
            "What SOP should I follow for Airflow outage?",
        ]

        for row_start in range(0, len(starter_prompts), 2):
            cols = st.columns(2)
            for idx, prompt_text in enumerate(starter_prompts[row_start:row_start + 2]):
                with cols[idx]:
                    if st.button(prompt_text, key=f"welcome_prompt_{row_start}_{idx}", width="stretch"):
                        queue_user_prompt(prompt_text)

for idx, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant":
            intent = msg.get("intent", "")
            label = INTENT_LABELS.get(intent, f":gray[{intent}]")
            st.caption(f"Chain: {label}")

            sn_resp = msg.get("sn_response")
            if sn_resp and idx == len(st.session_state.messages) - 1:
                render_sn_response(sn_resp, idx)
            else:
                st.markdown(msg["content"])
        else:
            st.markdown(msg["content"])

        if "steps" in msg and msg["steps"]:
            with st.expander("Graph Trace"):
                for i, step in enumerate(msg["steps"], 1):
                    st.text(f"  {i}. {step}")


# ── Handle user input ────────────────────────────────────────────────

def process_message(prompt: str):
    """Run the graph for a given prompt and return the result dict."""
    conversation_history = [
        {"role": m["role"], "content": m["content"]}
        for m in st.session_state.messages[:-1]
    ][-10:]

    state = {
        "question": prompt,
        "conversation_history": conversation_history,
        "documents": [],
        "steps": [],
        "retry_generation_count": 0,
        "kb_retry_count": 0,
        "kb_enriched": True,
    }

    if st.session_state.sn_session:
        state["sn_session"] = st.session_state.sn_session

    if intent_override is not None:
        state["intent"] = intent_override

    try:
        result = app.invoke(state)
    except Exception as e:
        result = {
            "generation": f"**Error:** {e}",
            "steps": ["error"],
            "intent": intent_override or "unknown",
        }

    return result


def handle_result(result: dict):
    """Persist session state and append the assistant message."""
    generation = result.get("generation", "No response generated.")
    steps = result.get("steps", [])
    intent_used = result.get("intent", "unknown")
    sn_response = result.get("sn_response")

    if intent_used == "SERVICENOW_INCIDENT":
        st.session_state.sn_session = result.get("sn_session")
        if sn_response:
            resp_type = sn_response.get("type", "")
            if resp_type == "disambiguation":
                st.session_state.sn_ui_phase = "showing_filters"
            elif resp_type in ("incident_list", "incident_stats"):
                st.session_state.sn_ui_phase = "showing_list"
            elif resp_type == "single_incident":
                st.session_state.sn_ui_phase = "showing_detail"
            elif resp_type in ("action_confirm", "action_needs_input"):
                st.session_state.sn_ui_phase = "awaiting_confirmation"
            elif resp_type == "action_result":
                st.session_state.sn_ui_phase = None
    else:
        st.session_state.sn_session = None
        st.session_state.sn_ui_phase = None

    msg_data = {
        "role": "assistant",
        "content": generation,
        "steps": steps,
        "intent": intent_used,
    }
    if sn_response:
        msg_data["sn_response"] = sn_response
        # Store sn_query so Refine filters can use it (session may change after later turns)
        resp_type = sn_response.get("type", "")
        if resp_type in ("incident_list", "incident_stats"):
            sn_sess = result.get("sn_session") or {}
            msg_data["sn_query"] = sn_sess.get("sn_query", "")

    st.session_state.messages.append(msg_data)


# Check for pending synthetic message (from widget click)
pending = st.session_state._pending_synthetic
if pending:
    st.session_state._pending_synthetic = None

    if pending.startswith("__direct_lookup__:"):
        inc_number = pending.split(":", 1)[1]
        sn_resp = do_direct_lookup(inc_number)
        fallback_text = sn_resp.get("text", "")
        msg_data = {
            "role": "assistant",
            "content": fallback_text,
            "steps": ["direct_lookup"],
            "intent": "SERVICENOW_INCIDENT",
            "sn_response": sn_resp,
        }
        st.session_state.messages.append(msg_data)
        st.session_state.sn_ui_phase = "showing_detail"
        st.rerun()
    elif pending.startswith("__refine_filters__:"):
        # Use sn_query from the message that has the incident list (session may have changed)
        msg_idx_str = pending.split(":", 1)[1]
        try:
            msg_idx = int(msg_idx_str)
            msg = st.session_state.messages[msg_idx] if msg_idx < len(st.session_state.messages) else {}
            base_query = msg.get("sn_query", "")
        except (ValueError, IndexError):
            base_query = ""
        sn_sess = dict(st.session_state.sn_session or {})
        sn_sess["sn_query"] = base_query or sn_sess.get("sn_query", "")
        sn_sess["accumulated_entities"] = {}
        sn_sess["force_disambiguate"] = True
        sn_sess.pop("awaiting", None)
        sn_sess.pop("pending_action", None)
        st.session_state.sn_session = sn_sess
        result = process_message("__refine_filters__")
        handle_result(result)
        st.rerun()
    elif pending == "__refine_filters_all__":
        # Force a broad disambiguation sample from all incidents.
        sn_sess = dict(st.session_state.sn_session or {})
        sn_sess["sn_query"] = ""
        sn_sess["accumulated_entities"] = {}
        sn_sess["force_disambiguate"] = True
        sn_sess.pop("awaiting", None)
        sn_sess.pop("pending_action", None)
        st.session_state.sn_session = sn_sess
        result = process_message("__refine_filters__")
        handle_result(result)
        st.rerun()
    elif pending == "__cancel_sn_action__":
        if st.session_state.sn_session:
            sn_sess = dict(st.session_state.sn_session)
            sn_sess.pop("pending_action", None)
            sn_sess["awaiting"] = None
            sn_sess["action_confirmed"] = False
            st.session_state.sn_session = sn_sess
        st.session_state.sn_ui_phase = None
        st.session_state.messages.append({
            "role": "assistant",
            "content": "Action cancelled.",
            "steps": ["action_cancelled"],
            "intent": "SERVICENOW_INCIDENT",
        })
        st.rerun()
    else:
        result = process_message(pending)
        handle_result(result)
        st.rerun()

# Normal chat input
if prompt := st.chat_input("Ask a question..."):
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Running graph..."):
            result = process_message(prompt)

        handle_result(result)

        generation = result.get("generation", "No response generated.")
        intent_used = result.get("intent", "unknown")
        sn_response = result.get("sn_response")
        steps = result.get("steps", [])

        label = INTENT_LABELS.get(intent_used, f":gray[{intent_used}]")
        st.caption(f"Chain: {label}")

        if sn_response:
            render_sn_response(sn_response, len(st.session_state.messages) - 1)
        else:
            st.markdown(generation)

        if steps:
            with st.expander("Graph Trace"):
                for i, step in enumerate(steps, 1):
                    st.text(f"  {i}. {step}")