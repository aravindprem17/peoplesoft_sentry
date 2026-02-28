"""
main.py - PeopleSoft Sentry FastAPI Orchestration Server
=========================================================
Coordinates:
  1. MCP tools (mcp_server.py)  – live DB data
  2. CAG cache  (cag_cache.py)  – pre-loaded SOPs
  3. Local LLM  (Ollama)        – reasoning / generation

Endpoints
---------
GET  /health              – Liveness probe
GET  /api/tools           – List available MCP tools
POST /api/health-check    – One-click automated health check
POST /api/chat            – Freeform chat with tool-calling loop
GET  /api/system-summary  – Raw system summary from MCP
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, AsyncIterator, Iterator

import ollama
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import cag_cache
import mcp_server

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LLM_MODEL   = os.getenv("SENTRY_LLM_MODEL", "llama3.3")   # or "deepseek-r1"
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [API] %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="PeopleSoft Sentry API",
    description="AIOps diagnostic engine for PeopleSoft Production Support",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []   # list of {"role": "user"|"assistant", "content": str}
    stream: bool = False


class HealthCheckResponse(BaseModel):
    summary: dict
    ib_errors: list[dict]
    process_errors: list[dict]
    analysis: str
    sops: list[dict]
    overall_status: str


# ---------------------------------------------------------------------------
# System prompt (CAG – SOPs baked in at startup)
# ---------------------------------------------------------------------------

_SOP_TEXT = cag_cache.get_all_sops_as_text()

SYSTEM_PROMPT = f"""
You are PeopleSoft Sentry, an expert AIOps assistant specialised in
PeopleSoft Production Support. You have access to live database tools
and a pre-loaded SOP (Standard Operating Procedure) knowledge base.

## Your Responsibilities
1. Diagnose PeopleSoft issues using real-time data from database tools.
2. Match errors to SOPs from the knowledge base and surface actionable remediation steps.
3. Provide concise Root-Cause Analysis (RCA) and clear "Next Steps".
4. Escalate clearly when issues are beyond automated resolution.

## Response Format
Always structure your response as:
- **🔍 Observation**: What you found in the data.
- **💡 Root Cause**: Most likely technical cause.
- **🛠 Next Steps**: Numbered, actionable remediation steps.
- **📋 SOP Applied**: Which SOP was used (if any).
- **🚨 Escalation**: Who to contact if steps don't resolve the issue.

## Available Tools
You may call the following tools by requesting them in your response:
- `get_ib_errors`       – Fetch IB message errors from PS_MSG_INST
- `get_process_errors`  – Fetch process errors from PSPRCSRQST
- `get_system_summary`  – Get high-level health counts

## Pre-Loaded SOP Knowledge Base (CAG)
The following SOPs are available. Apply the most relevant one when an error is identified.

{_SOP_TEXT}
""".strip()


# ---------------------------------------------------------------------------
# LLM helper
# ---------------------------------------------------------------------------

def _ollama_client() -> ollama.Client:
    return ollama.Client(host=OLLAMA_HOST)


def _build_ollama_tools() -> list[dict]:
    """Convert MCP tool definitions to Ollama tool format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t.get("parameters", {"type": "object", "properties": {}}),
            },
        }
        for t in mcp_server.TOOLS
    ]


def run_tool_calling_loop(
    user_message: str,
    history: list[dict],
) -> tuple[str, list[dict]]:
    """
    Agentic loop: send message → handle tool calls → return final answer.
    Returns (final_text, tool_results_for_display).
    """
    client      = _ollama_client()
    tools       = _build_ollama_tools()
    tool_log: list[dict] = []

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *history,
        {"role": "user", "content": user_message},
    ]

    # Agentic loop (max 5 rounds to prevent runaway)
    for _round in range(5):
        response = client.chat(
            model=LLM_MODEL,
            messages=messages,
            tools=tools,
        )

        msg = response.message

        # Append assistant turn
        messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": getattr(msg, "tool_calls", None)})

        # If no tool calls, we're done
        if not msg.tool_calls:
            return msg.content or "", tool_log

        # Execute each tool call
        for tc in msg.tool_calls:
            fn_name   = tc.function.name
            fn_params = tc.function.arguments or {}

            logger.info("LLM called tool: %s(%s)", fn_name, fn_params)
            result = mcp_server.execute_tool(fn_name, fn_params)
            tool_log.append({"tool": fn_name, "result": result})

            # Feed result back to model
            messages.append({
                "role":    "tool",
                "name":    fn_name,
                "content": json.dumps(result),
            })

    # Fallback if loop exhausted
    return "Analysis complete. Please review the tool outputs above.", tool_log


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "model": LLM_MODEL}


@app.get("/api/tools")
def list_tools():
    return {"tools": mcp_server.TOOLS}


@app.get("/api/system-summary")
def system_summary():
    return mcp_server.execute_tool("get_system_summary", {})


@app.post("/api/health-check", response_model=HealthCheckResponse)
def one_click_health_check():
    """
    Automated health check:
    1. Pull system summary, IB errors, and process errors via MCP.
    2. Look up SOPs for each error via CAG.
    3. Ask the LLM to synthesise an RCA.
    """
    # --- Step 1: Collect data via MCP tools ---------------------------------
    summary        = mcp_server.execute_tool("get_system_summary",   {})
    ib_result      = mcp_server.execute_tool("get_ib_errors",        {"hours_back": 24})
    process_result = mcp_server.execute_tool("get_process_errors",   {"hours_back": 24})

    ib_errors      = ib_result.get("errors", [])
    process_errors = process_result.get("errors", [])

    # --- Step 2: SOP lookup via CAG -----------------------------------------
    sop_hits: list[dict] = []

    for err in ib_errors:
        sop = cag_cache.lookup_sop(err.get("error_detail", ""))
        if sop:
            sop_hits.append({
                "source":      "IB",
                "transaction": err["transaction_id"],
                "sop_title":   sop.title,
                "resolution":  sop.resolution,
                "escalate_to": sop.escalate_to,
            })

    for err in process_errors:
        sop = cag_cache.lookup_sop(err.get("error_text", ""))
        if sop:
            sop_hits.append({
                "source":   "Process",
                "instance": err["process_instance"],
                "process":  err["process_name"],
                "sop_title":   sop.title,
                "resolution":  sop.resolution,
                "escalate_to": sop.escalate_to,
            })

    # --- Step 3: LLM synthesis -----------------------------------------------
    prompt = (
        f"Perform a PeopleSoft health check based on this data:\n\n"
        f"SYSTEM SUMMARY:\n{json.dumps(summary, indent=2)}\n\n"
        f"IB ERRORS:\n{json.dumps(ib_errors, indent=2)}\n\n"
        f"PROCESS ERRORS:\n{json.dumps(process_errors, indent=2)}\n\n"
        f"SOPs MATCHED:\n{json.dumps([{'title': s['sop_title'], 'escalate': s['escalate_to']} for s in sop_hits], indent=2)}\n\n"
        "Provide a concise Root-Cause Analysis and prioritised Next Steps."
    )

    analysis, _ = run_tool_calling_loop(prompt, [])

    overall_status = summary.get("overall_health", "UNKNOWN")

    return HealthCheckResponse(
        summary=summary,
        ib_errors=ib_errors,
        process_errors=process_errors,
        analysis=analysis,
        sops=sop_hits,
        overall_status=overall_status,
    )


@app.post("/api/chat")
def chat(req: ChatRequest):
    """Freeform chat endpoint with agentic tool-calling loop."""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    answer, tool_log = run_tool_calling_loop(req.message, req.history)

    return {
        "response":  answer,
        "tool_calls": tool_log,
    }
