"""
mcp_server.py - PeopleSoft Sentry MCP Server
=============================================
Defines the Model Context Protocol (MCP) tools that allow the LLM to
query PeopleSoft-related database tables for real-time diagnostic data.

Tables inspected:
  - PS_MSG_INST    : Integration Broker (IB) message instances / health
  - PSPRCSRQST     : Process Monitor requests / scheduler jobs
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [MCP] %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Database engine
# ---------------------------------------------------------------------------
# NOTE: Replace the connection string with a real Oracle DSN in production.
#       e.g. "oracle+cx_oracle://user:pass@host:1521/SID"
#
# For the POC we default to an in-memory SQLite database that is seeded with
# realistic mock PeopleSoft data so the project runs without any external DB.
DATABASE_URL = "sqlite:///./mock_peoplesoft.db"

engine = create_engine(DATABASE_URL, echo=False, future=True)

# ---------------------------------------------------------------------------
# Mock data seeding (SQLite only – skipped for real Oracle connections)
# ---------------------------------------------------------------------------

def seed_mock_data() -> None:
    """Create and populate mock PeopleSoft tables in the SQLite POC DB."""
    with engine.begin() as conn:
        # --- PS_MSG_INST (Integration Broker) --------------------------------
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS PS_MSG_INST (
                IB_TRANSACTIONID   TEXT PRIMARY KEY,
                MESSAGE_NAME       TEXT,
                MSG_STATUS         TEXT,   -- 1=New,7=Error,0=Done
                QUEUE_NAME         TEXT,
                PUBNODE            TEXT,
                SUBNODE            TEXT,
                DTTM_STAMP_SEC     TEXT,
                ERROR_MSG          TEXT
            )
        """))

        conn.execute(text("DELETE FROM PS_MSG_INST"))

        ib_rows = [
            ("TXN-1001", "VOUCHER_BUILD",      "0",  "VOUCHER_Q",   "PSFT_SRC", "ERP_DEST",  "2025-07-01 08:00:00", None),
            ("TXN-1002", "PO_RECEIPT_SYNC",    "7",  "PO_Q",        "PSFT_SRC", "WMS_DEST",  "2025-07-01 08:15:00",
             "SOAP Fault: Connection refused – target node WMS_DEST unreachable"),
            ("TXN-1003", "EMPLOYEE_SYNC",      "1",  "HR_Q",        "PSFT_SRC", "HCM_DEST",  "2025-07-01 08:30:00", None),
            ("TXN-1004", "GL_JOURNAL_IMPORT",  "7",  "FIN_Q",       "PSFT_SRC", "GL_DEST",   "2025-07-01 08:45:00",
             "Timeout: No response from GL_DEST after 30 s"),
            ("TXN-1005", "CUSTOMER_UPDATE",    "0",  "CRM_Q",       "PSFT_SRC", "CRM_DEST",  "2025-07-01 09:00:00", None),
        ]
        conn.execute(
            text("""
                INSERT INTO PS_MSG_INST
                  (IB_TRANSACTIONID,MESSAGE_NAME,MSG_STATUS,QUEUE_NAME,PUBNODE,SUBNODE,DTTM_STAMP_SEC,ERROR_MSG)
                VALUES (:1,:2,:3,:4,:5,:6,:7,:8)
            """),
            [dict(zip(["1","2","3","4","5","6","7","8"], r)) for r in ib_rows],
        )

        # --- PSPRCSRQST (Process Monitor) ------------------------------------
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS PSPRCSRQST (
                PRCSINSTANCE   INTEGER PRIMARY KEY,
                PRCSTYPE       TEXT,
                PRCSNAME       TEXT,
                RUNSTATUS      TEXT,   -- 14=Error,9=Success,7=Processing
                OPRID          TEXT,
                RUNCNTLID      TEXT,
                BEGINDTTM      TEXT,
                ENDDTTM        TEXT,
                OUTDESTFORMAT  TEXT,
                SERVERNM       TEXT,
                MESSAGE_TEXT   TEXT
            )
        """))

        conn.execute(text("DELETE FROM PSPRCSRQST"))

        prcs_rows = [
            (5001, "SQR Report",   "GLXLEDGR",   "9",  "PS_ADMIN", "GL_RPT_001", "2025-07-01 06:00:00", "2025-07-01 06:15:00", "PDF",  "PSNT",  None),
            (5002, "Application Engine", "AEMINILOAD", "14", "BATCH_USR", "MINI_LOAD", "2025-07-01 06:20:00", "2025-07-01 06:25:00", "LOG", "PSUNX",
             "SQL Error: ORA-01555 Snapshot too old – rollback segment too small"),
            (5003, "COBOL",        "PAYCHECK",   "7",  "PAYROLL",  "PAY_RUN_01", "2025-07-01 07:00:00", None,                   "LOG",  "PSUNX", None),
            (5004, "SQR Report",   "PYCHKUSA",   "14", "PAYROLL",  "PAY_CHK_02", "2025-07-01 07:10:00", "2025-07-01 07:12:00", "PDF",  "PSUNX",
             "ABN: PYCHKUSA – Company not found for Pay Run ID PAY_CHK_02"),
            (5005, "Application Engine", "FSPCYCMTH", "9", "FIN_ADM", "FIN_CYC_03","2025-07-01 05:00:00", "2025-07-01 05:45:00", "LOG", "PSNT",  None),
        ]
        conn.execute(
            text("""
                INSERT INTO PSPRCSRQST
                  (PRCSINSTANCE,PRCSTYPE,PRCSNAME,RUNSTATUS,OPRID,RUNCNTLID,BEGINDTTM,ENDDTTM,OUTDESTFORMAT,SERVERNM,MESSAGE_TEXT)
                VALUES (:1,:2,:3,:4,:5,:6,:7,:8,:9,:10,:11)
            """),
            [dict(zip([str(i) for i in range(1, 12)], r)) for r in prcs_rows],
        )

    logger.info("Mock PeopleSoft data seeded successfully.")


# ---------------------------------------------------------------------------
# MCP Tool Definitions
# ---------------------------------------------------------------------------

TOOLS: list[dict] = [
    {
        "name": "get_ib_errors",
        "description": (
            "Fetches Integration Broker message instances from PS_MSG_INST "
            "that are currently in an error state (MSG_STATUS = '7'). "
            "Returns transaction ID, message name, queue, nodes, timestamp, and error detail."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "hours_back": {
                    "type": "integer",
                    "description": "Look-back window in hours (default 24).",
                    "default": 24,
                }
            },
        },
    },
    {
        "name": "get_process_errors",
        "description": (
            "Fetches Process Monitor requests from PSPRCSRQST that are in "
            "error status (RUNSTATUS = '14'). "
            "Returns process instance, type, name, operator, run control, timestamps, and error text."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "hours_back": {
                    "type": "integer",
                    "description": "Look-back window in hours (default 24).",
                    "default": 24,
                }
            },
        },
    },
    {
        "name": "get_system_summary",
        "description": (
            "Returns a high-level health summary: counts of IB errors, "
            "process errors, and currently running processes."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
]


# ---------------------------------------------------------------------------
# Tool Execution
# ---------------------------------------------------------------------------

def execute_tool(tool_name: str, parameters: dict) -> dict[str, Any]:
    """
    Dispatch a tool call by name and return a structured result dict.
    This is the single entry-point used by main.py.
    """
    logger.info("Executing MCP tool: %s | params: %s", tool_name, parameters)

    handlers = {
        "get_ib_errors":        _tool_get_ib_errors,
        "get_process_errors":   _tool_get_process_errors,
        "get_system_summary":   _tool_get_system_summary,
    }

    handler = handlers.get(tool_name)
    if handler is None:
        return {"error": f"Unknown tool: {tool_name}"}

    try:
        return handler(parameters)
    except Exception as exc:
        logger.exception("Tool execution failed: %s", exc)
        return {"error": str(exc)}


# --- Individual tool implementations ----------------------------------------

def _tool_get_ib_errors(params: dict) -> dict:
    hours_back = int(params.get("hours_back", 24))
    cutoff = (datetime.utcnow() - timedelta(hours=hours_back)).strftime("%Y-%m-%d %H:%M:%S")

    with Session(engine) as session:
        rows = session.execute(
            text("""
                SELECT IB_TRANSACTIONID, MESSAGE_NAME, QUEUE_NAME,
                       PUBNODE, SUBNODE, DTTM_STAMP_SEC, ERROR_MSG
                FROM   PS_MSG_INST
                WHERE  MSG_STATUS = '7'
                  AND  DTTM_STAMP_SEC >= :cutoff
                ORDER  BY DTTM_STAMP_SEC DESC
            """),
            {"cutoff": cutoff},
        ).fetchall()

    errors = [
        {
            "transaction_id": r[0],
            "message_name":   r[1],
            "queue":          r[2],
            "pub_node":       r[3],
            "sub_node":       r[4],
            "timestamp":      r[5],
            "error_detail":   r[6],
        }
        for r in rows
    ]

    return {
        "tool": "get_ib_errors",
        "count": len(errors),
        "errors": errors,
    }


def _tool_get_process_errors(params: dict) -> dict:
    hours_back = int(params.get("hours_back", 24))
    cutoff = (datetime.utcnow() - timedelta(hours=hours_back)).strftime("%Y-%m-%d %H:%M:%S")

    with Session(engine) as session:
        rows = session.execute(
            text("""
                SELECT PRCSINSTANCE, PRCSTYPE, PRCSNAME, OPRID,
                       RUNCNTLID, BEGINDTTM, ENDDTTM, SERVERNM, MESSAGE_TEXT
                FROM   PSPRCSRQST
                WHERE  RUNSTATUS = '14'
                  AND  BEGINDTTM >= :cutoff
                ORDER  BY BEGINDTTM DESC
            """),
            {"cutoff": cutoff},
        ).fetchall()

    errors = [
        {
            "process_instance": r[0],
            "process_type":     r[1],
            "process_name":     r[2],
            "operator":         r[3],
            "run_control":      r[4],
            "begin_dttm":       r[5],
            "end_dttm":         r[6],
            "server":           r[7],
            "error_text":       r[8],
        }
        for r in rows
    ]

    return {
        "tool": "get_process_errors",
        "count": len(errors),
        "errors": errors,
    }


def _tool_get_system_summary(params: dict) -> dict:  # noqa: ARG001
    with Session(engine) as session:
        ib_errors = session.execute(
            text("SELECT COUNT(*) FROM PS_MSG_INST WHERE MSG_STATUS = '7'")
        ).scalar()

        proc_errors = session.execute(
            text("SELECT COUNT(*) FROM PSPRCSRQST WHERE RUNSTATUS = '14'")
        ).scalar()

        proc_running = session.execute(
            text("SELECT COUNT(*) FROM PSPRCSRQST WHERE RUNSTATUS = '7'")
        ).scalar()

        ib_total = session.execute(
            text("SELECT COUNT(*) FROM PS_MSG_INST")
        ).scalar()

        proc_total = session.execute(
            text("SELECT COUNT(*) FROM PSPRCSRQST")
        ).scalar()

    return {
        "tool": "get_system_summary",
        "ib_total_messages":     ib_total,
        "ib_error_count":        ib_errors,
        "process_total":         proc_total,
        "process_error_count":   proc_errors,
        "process_running_count": proc_running,
        "overall_health":        "DEGRADED" if (ib_errors or proc_errors) else "HEALTHY",
    }


# ---------------------------------------------------------------------------
# Bootstrap DB on import
# ---------------------------------------------------------------------------
seed_mock_data()
