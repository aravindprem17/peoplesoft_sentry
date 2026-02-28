# 🛡️ PeopleSoft Sentry

> **An AIOps Diagnostic Engine for PeopleSoft Production Support**
> — powered by a Local LLM, Model Context Protocol (MCP), and Cache-Augmented Generation (CAG).

---

## 📌 Overview

PeopleSoft Sentry is a production-ready Proof of Concept that automates first-line diagnosis of PeopleSoft incidents. Instead of having support engineers manually query Process Monitor and Integration Broker logs, Sentry:

1. **Pulls live data** from PeopleSoft DB tables via MCP tools.
2. **Matches errors** to curated Standard Operating Procedures (SOPs) stored in a CAG cache.
3. **Generates a root-cause analysis** and prioritised remediation steps using a fully local LLM (no data leaves your network).
4. **Presents results** in a clean Streamlit dashboard with a one-click health check and a freeform chat interface.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Streamlit (app.py)                    │
│  ┌──────────────────┐   ┌──────────────────────────────┐ │
│  │ Health Dashboard │   │     AI Chat Interface        │ │
│  └────────┬─────────┘   └──────────────┬───────────────┘ │
└───────────┼─────────────────────────────┼─────────────────┘
            │  HTTP (REST)                │
┌───────────▼─────────────────────────────▼─────────────────┐
│                    FastAPI (main.py)                        │
│                                                             │
│   ┌───────────────┐   ┌───────────────┐  ┌─────────────┐  │
│   │  MCP Server   │   │  CAG Cache    │  │  Ollama LLM │  │
│   │ (mcp_server)  │   │ (cag_cache)   │  │ llama3.3 /  │  │
│   │               │   │               │  │ deepseek-r1 │  │
│   │ get_ib_errors │   │ SOP Library   │  └─────────────┘  │
│   │ get_proc_errs │   │ lookup_sop()  │                    │
│   │ get_summary   │   │               │                    │
│   └───────┬───────┘   └───────────────┘                    │
└───────────┼────────────────────────────────────────────────┘
            │  SQLAlchemy
┌───────────▼───────────────────┐
│   PeopleSoft Oracle DB        │
│  ┌─────────────┐ ┌──────────┐ │
│  │ PS_MSG_INST │ │PSPRCSRQST│ │
│  └─────────────┘ └──────────┘ │
└───────────────────────────────┘
```

---

## ⚙️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Streamlit |
| Backend API | FastAPI + Uvicorn |
| LLM | Ollama (`llama3.3` or `deepseek-r1`) |
| DB ORM | SQLAlchemy (SQLite for POC / Oracle for production) |
| Intelligence: MCP | Custom tool definitions for PS DB inspection |
| Intelligence: CAG | In-memory SOP cache baked into the system prompt |

---

## 📁 Project Structure

```
peoplesoft_sentry/
├── mcp_server.py     # MCP tool definitions + DB queries
├── cag_cache.py      # SOP library + CAG system-prompt builder
├── main.py           # FastAPI orchestration server
├── app.py            # Streamlit dashboard
├── requirements.txt  # Python dependencies
└── README.md         # This file
```

---

## 🚀 Quick Start

### Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Python | ≥ 3.11 | Runtime |
| [Ollama](https://ollama.ai) | latest | Local LLM server |
| `llama3.3` or `deepseek-r1` | via Ollama | Reasoning model |

### 1 — Install Ollama and pull a model

```bash
# Install Ollama (macOS / Linux)
curl -fsSL https://ollama.ai/install.sh | sh

# Pull the model (choose one)
ollama pull llama3.3
# or
ollama pull deepseek-r1
```

### 2 — Clone and install dependencies

```bash
git clone https://github.com/yourorg/peoplesoft-sentry.git
cd peoplesoft-sentry

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### 3 — (Optional) Configure environment variables

```bash
# .env
SENTRY_LLM_MODEL=llama3.3          # or deepseek-r1
OLLAMA_HOST=http://localhost:11434  # default
# DATABASE_URL=oracle+oracledb://user:pass@host:1521/SID  # for real Oracle
```

### 4 — Start the FastAPI backend

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

The API will be available at `http://localhost:8000`.
Interactive docs: `http://localhost:8000/docs`

### 5 — Start the Streamlit frontend

```bash
streamlit run app.py
```

Open `http://localhost:8501` in your browser.

---

## 🖥️ Dashboard Features

### One-Click Health Check
Click **"Run One-Click Health Check"** to trigger a full automated scan:
- Queries `PS_MSG_INST` for IB errors in the last 24 hours.
- Queries `PSPRCSRQST` for Process Monitor errors in the last 24 hours.
- Matches each error to an SOP from the CAG cache.
- Sends all findings to the LLM for RCA synthesis.
- Displays metric cards, error details, SOPs, and the AI analysis.

### AI Chat Interface
Ask natural-language questions like:
- *"Are there any IB errors right now?"*
- *"Why did AEMINILOAD fail and how do I fix it?"*
- *"Give me a full system health summary."*

The AI will call MCP tools autonomously, apply SOP knowledge, and respond.

---

## 🔌 MCP Tools

| Tool | Table | Description |
|------|-------|-------------|
| `get_ib_errors` | `PS_MSG_INST` | IB messages with `MSG_STATUS = '7'` (Error) |
| `get_process_errors` | `PSPRCSRQST` | Processes with `RUNSTATUS = '14'` (Error) |
| `get_system_summary` | Both | Health counts and overall status |

---

## 📚 SOP Knowledge Base (CAG)

SOPs are pre-loaded into the LLM system prompt at startup for zero-latency retrieval:

| SOP Key | Trigger Pattern | Summary |
|---------|----------------|---------|
| `ora-01555` | `ORA-01555`, `snapshot too old` | Increase UNDO_RETENTION + undo tablespace |
| `ib-connection-refused` | `Connection refused` | Fix node URL / firewall / Gateway config |
| `ib-timeout` | `Timeout`, `No response` | Increase connector timeout, check payload size |
| `pychkusa-company-not-found` | `Company not found`, `PYCHKUSA` | Validate Company in Run Control |
| `generic-process-error` | (fallback) | Review message log and escalate |

To add new SOPs, edit the `_SOP_LIBRARY` list in `cag_cache.py`.

---

## 🔧 Connecting to Real Oracle / PeopleSoft DB

1. Install `oracledb`: `pip install oracledb`
2. Set `DATABASE_URL` in your environment:
   ```
   DATABASE_URL=oracle+oracledb://PSFT_APP:password@db-host:1521/HRPRD
   ```
3. Remove the `seed_mock_data()` call in `mcp_server.py`.
4. Ensure the DB user has `SELECT` on `PS_MSG_INST` and `PSPRCSRQST`.

---

## 🛣️ Roadmap

- [ ] Vector-store SOP retrieval (RAG) for large SOP libraries
- [ ] Slack / Teams alerting integration
- [ ] PeopleSoft Application Engine trace log analysis
- [ ] Automated ticket creation in ServiceNow / Jira
- [ ] Multi-environment support (DEV / QA / PRD toggle)
- [ ] Historical trend charts in dashboard

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

## 🤝 Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

---

*Built with ❤️ by the PeopleSoft Platform Engineering team.*
