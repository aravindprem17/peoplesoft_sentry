"""
app.py - PeopleSoft Sentry Streamlit Dashboard
===============================================
Provides:
  - One-Click Health Check button
  - Live metric cards (IB errors, Process errors, overall status)
  - SOP resolution cards
  - LLM-generated Root-Cause Analysis
  - Chat interface for ad-hoc queries
"""

from __future__ import annotations

import time
from typing import Any

import requests
import streamlit as st

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API_BASE = "http://localhost:8000"

# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="PeopleSoft Sentry",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    /* Header */
    .sentry-header {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
        padding: 1.5rem 2rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        color: white;
    }
    .sentry-header h1 { margin: 0; font-size: 2rem; }
    .sentry-header p  { margin: 0.3rem 0 0; opacity: 0.75; font-size: 0.95rem; }

    /* Metric cards */
    .metric-card {
        background: #1e1e2e;
        border-radius: 10px;
        padding: 1rem 1.2rem;
        border-left: 4px solid #4f46e5;
        color: white;
        margin-bottom: 0.5rem;
    }
    .metric-card.error  { border-left-color: #ef4444; }
    .metric-card.warn   { border-left-color: #f59e0b; }
    .metric-card.ok     { border-left-color: #22c55e; }
    .metric-card h3     { margin: 0; font-size: 2rem; }
    .metric-card span   { font-size: 0.85rem; opacity: 0.7; }

    /* SOP cards */
    .sop-card {
        background: #1e2030;
        border-radius: 10px;
        padding: 1rem;
        border: 1px solid #2a2a4a;
        margin-bottom: 0.75rem;
    }
    .sop-card h4 { color: #818cf8; margin-top: 0; }

    /* Chat messages */
    .chat-user      { background:#2d3748; border-radius:8px; padding:0.6rem 1rem; margin:0.3rem 0; }
    .chat-assistant { background:#1a2035; border-radius:8px; padding:0.6rem 1rem; margin:0.3rem 0;
                      border-left: 3px solid #818cf8; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.image("https://www.oracle.com/a/ocom/img/cb71-peoplesoft-logo.png", width=160)
    st.markdown("---")
    st.markdown("### ⚙️ Configuration")
    api_url = st.text_input("API Base URL", value=API_BASE)
    st.markdown("---")
    st.markdown(
        "**PeopleSoft Sentry** is an AIOps tool that uses a local LLM "
        "to diagnose PeopleSoft Production Support issues in real time.\n\n"
        "**Components**\n"
        "- 🔌 MCP Server (DB tools)\n"
        "- 📚 CAG Cache (SOPs)\n"
        "- 🤖 Local LLM via Ollama\n"
        "- ⚡ FastAPI Backend\n"
    )
    st.markdown("---")
    st.caption("v1.0.0 | Built with FastAPI + Streamlit + Ollama")

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.markdown(
    """
    <div class="sentry-header">
        <h1>🛡️ PeopleSoft Sentry</h1>
        <p>AIOps Diagnostic Engine · Powered by Local LLM + MCP + CAG</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
if "chat_history"  not in st.session_state:
    st.session_state.chat_history = []
if "health_result" not in st.session_state:
    st.session_state.health_result = None

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def call_api(method: str, path: str, **kwargs) -> dict | None:
    try:
        resp = requests.request(method, f"{api_url}{path}", timeout=120, **kwargs)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        st.error("❌ Cannot connect to PeopleSoft Sentry API. Is `main.py` running?")
    except requests.exceptions.Timeout:
        st.error("⏱️ API request timed out.")
    except Exception as exc:
        st.error(f"API Error: {exc}")
    return None


def status_color(status: str) -> str:
    if status == "HEALTHY":
        return "ok"
    if status == "DEGRADED":
        return "error"
    return "warn"


def render_metric(label: str, value: Any, css_class: str = "") -> None:
    st.markdown(
        f'<div class="metric-card {css_class}"><h3>{value}</h3><span>{label}</span></div>',
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_dashboard, tab_chat = st.tabs(["📊 Health Dashboard", "💬 AI Chat"])

# ============================================================================
# TAB 1 – Health Dashboard
# ============================================================================
with tab_dashboard:
    col_btn, col_status = st.columns([3, 1])

    with col_btn:
        run_check = st.button(
            "🔍 Run One-Click Health Check",
            type="primary",
            use_container_width=True,
            help="Queries the PeopleSoft DB, matches SOPs, and asks the LLM for an RCA.",
        )

    with col_status:
        if st.button("🔄 Clear Results", use_container_width=True):
            st.session_state.health_result = None
            st.rerun()

    if run_check:
        with st.spinner("🤖 Querying database and running LLM analysis…"):
            result = call_api("POST", "/api/health-check")
            if result:
                st.session_state.health_result = result
                st.success("Health check complete!")
            else:
                st.session_state.health_result = None

    # ---- Display results ---------------------------------------------------
    result: dict | None = st.session_state.health_result

    if result:
        # ---- Metric row
        st.markdown("### 📈 System Metrics")
        m1, m2, m3, m4 = st.columns(4)

        ov_status  = result.get("overall_status", "UNKNOWN")
        summary    = result.get("summary", {})
        ib_errs    = result.get("ib_errors", [])
        proc_errs  = result.get("process_errors", [])

        with m1:
            css = status_color(ov_status)
            render_metric("Overall Health", ov_status, css)
        with m2:
            render_metric("IB Errors (24h)",  len(ib_errs),   "error" if ib_errs  else "ok")
        with m3:
            render_metric("Process Errors (24h)", len(proc_errs), "error" if proc_errs else "ok")
        with m4:
            render_metric("Running Processes", summary.get("process_running_count", "–"), "warn")

        st.markdown("---")

        # ---- IB Errors
        if ib_errs:
            st.markdown("### 🔌 Integration Broker Errors")
            for err in ib_errs:
                with st.expander(f"❌ {err['message_name']} | TXN: {err['transaction_id']}", expanded=True):
                    col_a, col_b = st.columns(2)
                    col_a.metric("Queue",    err.get("queue",    "–"))
                    col_b.metric("Sub Node", err.get("sub_node", "–"))
                    st.caption(f"🕐 {err.get('timestamp', '–')}")
                    if err.get("error_detail"):
                        st.error(f"Error: {err['error_detail']}")

        # ---- Process Errors
        if proc_errs:
            st.markdown("### ⚙️ Process Monitor Errors")
            for err in proc_errs:
                with st.expander(
                    f"❌ {err['process_name']} (Instance: {err['process_instance']})", expanded=True
                ):
                    col_a, col_b, col_c = st.columns(3)
                    col_a.metric("Type",       err.get("process_type", "–"))
                    col_b.metric("Operator",   err.get("operator",     "–"))
                    col_c.metric("Server",     err.get("server",       "–"))
                    st.caption(f"🕐 Started: {err.get('begin_dttm', '–')}")
                    if err.get("error_text"):
                        st.error(f"Error: {err['error_text']}")

        # ---- SOPs
        sops = result.get("sops", [])
        if sops:
            st.markdown("### 📋 Matched SOPs & Remediation Steps")
            for sop in sops:
                source_badge = "🔌 IB" if sop.get("source") == "IB" else "⚙️ Process"
                with st.expander(f"{source_badge} | {sop['sop_title']}", expanded=True):
                    st.markdown(f"**Escalate To:** `{sop['escalate_to']}`")
                    st.markdown("**Resolution Steps:**")
                    for step in sop.get("resolution", []):
                        st.markdown(f"  {step}")

        # ---- LLM RCA
        st.markdown("### 🤖 AI Root-Cause Analysis")
        analysis = result.get("analysis", "No analysis available.")
        st.markdown(
            f'<div style="background:#1a2035;border-left:4px solid #818cf8;'
            f'border-radius:8px;padding:1rem;color:#e2e8f0;">{analysis}</div>',
            unsafe_allow_html=True,
        )

    else:
        # Placeholder when no check has been run
        st.info(
            "Click **Run One-Click Health Check** to start a full PeopleSoft "
            "diagnostic scan. The AI will query the database, match errors to SOPs, "
            "and generate a root-cause analysis."
        )

# ============================================================================
# TAB 2 – Chat Interface
# ============================================================================
with tab_chat:
    st.markdown("### 💬 Ask PeopleSoft Sentry")
    st.caption(
        "Ask anything about your PeopleSoft environment. "
        "The AI will use live DB tools and SOP knowledge to answer."
    )

    # ---- Chat history display
    for msg in st.session_state.chat_history:
        if msg["role"] == "user":
            with st.chat_message("user"):
                st.write(msg["content"])
        else:
            with st.chat_message("assistant", avatar="🛡️"):
                st.markdown(msg["content"])
                if msg.get("tool_calls"):
                    with st.expander("🔧 Tools Used", expanded=False):
                        for tc in msg["tool_calls"]:
                            st.json(tc)

    # ---- Input
    user_input = st.chat_input("e.g. 'Are there any IB errors right now?' or 'Why did AEMINILOAD fail?'")

    if user_input:
        # Add user message to display
        st.session_state.chat_history.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.write(user_input)

        # Call API
        with st.chat_message("assistant", avatar="🛡️"):
            with st.spinner("🤖 Thinking…"):
                # Build history for API (exclude tool_calls key)
                api_history = [
                    {"role": m["role"], "content": m["content"]}
                    for m in st.session_state.chat_history[:-1]
                ]
                data = call_api(
                    "POST",
                    "/api/chat",
                    json={"message": user_input, "history": api_history},
                )

            if data:
                answer    = data.get("response", "No response received.")
                tool_log  = data.get("tool_calls", [])

                st.markdown(answer)

                if tool_log:
                    with st.expander("🔧 Tools Used", expanded=False):
                        for tc in tool_log:
                            st.json(tc)

                st.session_state.chat_history.append(
                    {"role": "assistant", "content": answer, "tool_calls": tool_log}
                )

    # ---- Clear chat
    if st.session_state.chat_history:
        if st.button("🗑️ Clear Chat History"):
            st.session_state.chat_history = []
            st.rerun()

    # ---- Suggested prompts
    if not st.session_state.chat_history:
        st.markdown("#### 💡 Try asking…")
        prompts = [
            "What IB errors occurred in the last 24 hours?",
            "Which processes are currently in error status?",
            "Give me a full health check summary.",
            "What's the root cause of ORA-01555 and how do I fix it?",
        ]
        cols = st.columns(2)
        for i, prompt in enumerate(prompts):
            with cols[i % 2]:
                if st.button(f"❓ {prompt}", key=f"sugg_{i}", use_container_width=True):
                    st.session_state.chat_history.append({"role": "user", "content": prompt})
                    st.rerun()
