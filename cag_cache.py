"""
cag_cache.py - Cache-Augmented Generation (CAG) SOP Store
==========================================================
Pre-loads Standard Operating Procedures (SOPs) into memory so they are
instantly available to the LLM without extra retrieval latency.

Structure
---------
Each SOP entry is keyed by an error pattern (matched via substring search)
and contains:
  - title        : Short human-readable name
  - root_cause   : Likely technical cause
  - symptoms     : What to look for
  - resolution   : Step-by-step fix
  - escalate_to  : Team / ticket queue if SOP does not resolve
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SOP:
    key: str
    title: str
    root_cause: str
    symptoms: list[str]
    resolution: list[str]
    escalate_to: str
    tags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# SOP Library  (extend this list to grow the knowledge base)
# ---------------------------------------------------------------------------
_SOP_LIBRARY: list[SOP] = [
    SOP(
        key="ora-01555",
        title="ORA-01555: Snapshot Too Old",
        root_cause=(
            "The Oracle rollback/undo segment was too small or the UNDO_RETENTION "
            "parameter is too low, causing long-running queries to lose read consistency."
        ),
        symptoms=[
            "PSPRCSRQST shows RUNSTATUS=14 (Error) for Application Engine jobs",
            "Message log contains 'ORA-01555 snapshot too old'",
            "Typically seen during month-end batch runs or large data loads",
        ],
        resolution=[
            "1. Verify UNDO_RETENTION (recommended ≥ 3600 s): "
            "   SELECT VALUE FROM V$PARAMETER WHERE NAME='undo_retention';",
            "2. Increase UNDO_RETENTION: "
            "   ALTER SYSTEM SET UNDO_RETENTION=7200 SCOPE=BOTH;",
            "3. Check undo tablespace size and add a datafile if < 10 GB free:",
            "   ALTER TABLESPACE UNDOTBS1 ADD DATAFILE SIZE 4G AUTOEXTEND ON;",
            "4. Re-run the failed process from Process Monitor (Actions → Restart).",
            "5. Schedule large batch jobs during off-peak hours to reduce contention.",
        ],
        escalate_to="DBA Team – Ticket Queue: ORA-DB-PERF",
        tags=["oracle", "undo", "ae", "batch"],
    ),
    SOP(
        key="ib-connection-refused",
        title="IB Error: Target Node Connection Refused",
        root_cause=(
            "The Integration Broker cannot establish a TCP/HTTP connection to the "
            "target (subscriber) node. The remote endpoint is down, firewalled, or "
            "the Gateway URL is mis-configured."
        ),
        symptoms=[
            "PS_MSG_INST shows MSG_STATUS=7 with 'Connection refused' in ERROR_MSG",
            "Multiple messages queued for the same sub-node",
            "IB Monitor shows node ping failures",
        ],
        resolution=[
            "1. Ping / curl the target node URL from the PeopleSoft App Server:",
            "   curl -v https://<target-node-url>/PSIGW/PeopleSoftServiceListeningConnector",
            "2. Check PeopleSoft Gateway URL (PeopleTools → Integration Broker → Gateways).",
            "3. Verify the target node is active (Node Definitions → Status = Active).",
            "4. Check firewall rules between source and target VLAN.",
            "5. Restart the Integration Gateway (weblogic managed server) if needed.",
            "6. Use IB Monitor → Service Operations → Re-submit errored transactions.",
        ],
        escalate_to="Middleware / Integration Team – Queue: IB-CONNECT",
        tags=["ib", "integration broker", "node", "connectivity"],
    ),
    SOP(
        key="ib-timeout",
        title="IB Error: Target Node Timeout",
        root_cause=(
            "The subscriber node did not respond within the configured timeout window. "
            "Causes include slow target system, large payload, or network latency."
        ),
        symptoms=[
            "ERROR_MSG contains 'Timeout' or 'No response'",
            "MSG_STATUS=7 on PS_MSG_INST rows",
            "Sporadic failures rather than complete outage",
        ],
        resolution=[
            "1. Check target node response time – run a test ping from IB Monitor.",
            "2. Increase Gateway timeout (Gateway Properties → Connector timeout).",
            "3. Analyze payload size – enable chunking for messages > 5 MB.",
            "4. Review target system performance metrics during the failure window.",
            "5. Re-submit failed messages via IB Monitor after root cause is resolved.",
        ],
        escalate_to="Integration Team – Queue: IB-PERF",
        tags=["ib", "timeout", "performance"],
    ),
    SOP(
        key="pychkusa-company-not-found",
        title="Paycheck (PYCHKUSA) – Company Not Found",
        root_cause=(
            "The Pay Run ID references a Company that does not exist or is inactive "
            "in PS_COMPANY_TBL, or the Run Control was set up with incorrect parameters."
        ),
        symptoms=[
            "PSPRCSRQST RUNSTATUS=14 for process PYCHKUSA",
            "Message: 'Company not found for Pay Run ID'",
            "Payroll administrators unable to confirm paycheck printing",
        ],
        resolution=[
            "1. Verify the Company code in the Run Control:",
            "   SELECT * FROM PS_RC_PAY WHERE OPRID=:oprid AND RUN_CNTL_ID=:runcntl;",
            "2. Confirm Company is active:",
            "   SELECT EFFDT, EFF_STATUS FROM PS_COMPANY_TBL WHERE COMPANY=:company ORDER BY EFFDT DESC;",
            "3. If Company is inactive, re-activate via Set Up HCM → Foundation Tables → Company.",
            "4. Correct the Run Control and re-run PYCHKUSA from Process Monitor.",
            "5. Notify Payroll Manager before re-run to confirm pay cycle details.",
        ],
        escalate_to="Payroll / HCM Functional Team – Queue: PAY-CONFIG",
        tags=["payroll", "pychkusa", "company", "hcm"],
    ),
    SOP(
        key="generic-process-error",
        title="Generic Process Monitor Error",
        root_cause="Process ended abnormally – review message log for specific ORA- or ABN: codes.",
        symptoms=[
            "RUNSTATUS=14 in PSPRCSRQST",
            "No specific error pattern matched",
        ],
        resolution=[
            "1. Open Process Monitor, click on the failed Process Instance.",
            "2. Click 'Message Log' to review detailed error output.",
            "3. Check the server log: $PS_LOGDIR/<server>/<process>_<instance>.log",
            "4. Search internal knowledge base for the specific error code.",
            "5. Escalate to Technical Support with log file attached.",
        ],
        escalate_to="PeopleSoft Technical Support – Queue: PSFT-GENERAL",
        tags=["generic", "process"],
    ),
]

# Pre-index by key for O(1) lookup and compile tag sets
_INDEX: dict[str, SOP] = {sop.key: sop for sop in _SOP_LIBRARY}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_all_sops_as_text() -> str:
    """
    Serialise the entire SOP library into a structured text block suitable
    for inclusion in an LLM system prompt (CAG technique).
    """
    blocks = []
    for sop in _SOP_LIBRARY:
        lines = [
            f"## SOP: {sop.title}",
            f"**Root Cause:** {sop.root_cause}",
            "**Symptoms:**",
            *[f"  - {s}" for s in sop.symptoms],
            "**Resolution Steps:**",
            *[f"  {r}" for r in sop.resolution],
            f"**Escalate To:** {sop.escalate_to}",
        ]
        blocks.append("\n".join(lines))
    return "\n\n---\n\n".join(blocks)


def lookup_sop(error_text: str) -> Optional[SOP]:
    """
    Find the most relevant SOP for a given error string using keyword
    matching. Returns the best match or the generic fallback.
    """
    if not error_text:
        return None

    lower = error_text.lower()

    # Priority-ordered pattern → SOP key mapping
    patterns: list[tuple[str, str]] = [
        (r"ora-01555|snapshot too old",                       "ora-01555"),
        (r"connection refused",                               "ib-connection-refused"),
        (r"timeout|no response",                              "ib-timeout"),
        (r"company not found|pychkusa",                       "pychkusa-company-not-found"),
    ]

    for pattern, key in patterns:
        if re.search(pattern, lower):
            return _INDEX.get(key)

    return _INDEX.get("generic-process-error")


def format_sop_for_display(sop: SOP) -> str:
    """Return a nicely formatted string for UI/LLM consumption."""
    return (
        f"**📋 SOP: {sop.title}**\n\n"
        f"**Root Cause:** {sop.root_cause}\n\n"
        f"**Resolution Steps:**\n"
        + "\n".join(sop.resolution)
        + f"\n\n**Escalate To:** `{sop.escalate_to}`"
    )
