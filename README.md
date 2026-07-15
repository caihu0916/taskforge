# TaskForge - AI Agent OS for Solo Entrepreneurs

> 半开源 | 30+ Agent 角色 | 工作流 DSL | Tauri 桌面端 — 本地优先，AI 执行，人类拍板

[![License: BSL 1.1](https://img.shields.io/badge/License-BSL%201.1-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com)
[![Tauri 2](https://img.shields.io/badge/Tauri-2.0-FFC131.svg)](https://tauri.app)
[![React 19](https://img.shields.io/badge/React-19-61DAFB.svg)](https://react.dev)

**English** | [中文](README_zh.md)

---

## What is TaskForge?

TaskForge is an **AI Agent Operating System** designed for solo entrepreneurs and small teams. It orchestrates multiple AI agents to handle business tasks autonomously while keeping humans in control of key decisions.

### Key Features

- **30+ Agent Roles** — From product managers to finance analysts, each role follows PDCA (Plan-Do-Check-Act) methodology
- **Workflow DSL** — Express complex business processes with: `agent()`, `parallel()`, `pipeline()`, `phase()`, `if_else()`, `loop()`, `switch()`
- **Dual-Mode LLM** — Local (Ollama, free) or Remote (SaaS API keys for OpenAI, Claude, etc.)
- **Template Market** — Pre-built templates for finance reports, CRM follow-ups, content creation, and more
- **Tauri Desktop** — Cross-platform desktop app (Windows / macOS / Linux)
- **A2A Protocol** — Agent-to-Agent interoperability for distributed workflows
- **Local-First** — Your data stays on your machine. Cloud sync is optional.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Routes Layer (FastAPI, 2000+ REST endpoints)       │
├─────────────────────────────────────────────────────┤
│  Engine Layer (Agent / LLM / Workflow / Template)    │
│  ├─ Agent: 30+ roles, PDCA pipeline, sub-agent pool │
│  ├─ LLM: 20+ providers, local & remote routing      │
│  ├─ Workflow: DAG compiler, NL→DAG, step executors   │
│  └─ Template: YAML-defined, parameterized scenarios  │
├─────────────────────────────────────────────────────┤
│  Infra Layer (Config / Auth / Database / SecureStore)│
├─────────────────────────────────────────────────────┤
│  Closed-Source Extensions (Pro features)             │
│  ├─ Billing & Credits                               │
│  ├─ Connectors (WeChat/Feishu/DingTalk/Kingdee)     │
│  └─ Advanced Analytics & Attribution                │
└─────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+ (for frontend)
- [Ollama](https://ollama.com) (for local LLM, optional)

### 1. Install & Run Backend

```bash
# Clone the repo
git clone https://github.com/caihu0916/taskforge.git
cd taskforge

# Install dependencies
pip install -e ".[dev]"

# Start the server
python app.py
# → http://localhost:8001
```

### 2. Install & Run Frontend

```bash
cd web
npm install
npm run dev
# → http://localhost:3000
```

### 3. Enable LLM

**Option A: Local (Free, Recommended)**

```bash
# Install Ollama: https://ollama.com/download
ollama pull qwen2.5:7b
# TaskForge will auto-detect Ollama on localhost:11434
```

**Option B: Remote API Key**

```bash
# Set your API key in .env
echo "LLM_API_KEY=your-key-here" >> .env
```

### 4. Run Example Scene

```bash
python examples/scenes/finance_report_demo.py
```

## Workflow DSL Examples

```python
from src.engine.workflow.dsl import pipeline, agent, parallel, phase

# Simple agent task
result = agent("finance_analyst").do("Analyze Q3 revenue trends")

# Parallel execution
result = parallel(
    agent("researcher").do("Market analysis"),
    agent("analyst").do("Financial modeling"),
    agent("writer").do("Draft report outline"),
)

# Full pipeline with phases
result = pipeline(
    phase("plan",   agent("pm").do("Create project plan")),
    phase("exec",   parallel(
        agent("dev").do("Build feature"),
        agent("designer").do("Create mockups"),
    )),
    phase("check",  agent("qa").do("Review deliverables")),
    phase("act",    agent("pm").do("Finalize and deploy")),
)
```

## Agent Roles

| Category | Roles |
|----------|-------|
| **Core** | PM, Developer, Designer, QA, Analyst, Writer, Researcher |
| **Business** | Finance, Legal, Marketing, Sales, HR, Operations |
| **Code** | Backend, Frontend, DevOps, Data Engineer |

All roles follow the PDCA pipeline: Plan → Do → Check → Act

## Pro Features (Closed-Source)

The open-source edition includes core Agent, LLM, Workflow, and Template functionality. Pro features are available via a separate package:

- **Billing & Credits** — Usage tracking and payment integration
- **Connectors** — WeChat Work, Feishu, DingTalk, Kingdee, Yonyou
- **Advanced Analytics** — Attribution tracking, ROI dashboards
- **Device Fingerprint** — Anti-abuse and license enforcement

Pro features require a license key. See [pricing](https://cloud.taskos.online/pricing).

## Development

```bash
# Backend lint & test
ruff check src/ tests/ && ruff format
pytest tests/unit/ -v

# Frontend type check & build
cd web && npx tsc --noEmit && npx vite build
```

## License

TaskForge is licensed under the **Business Source License 1.1 (BSL 1.1)**:

- **Non-production use** (evaluation, testing, development) is free
- **Production use** requires a commercial license
- On **2029-06-22**, the license automatically converts to **Apache License 2.0**

See [LICENSE](LICENSE) for details.

## Links

- 🌐 [SaaS Platform](https://cloud.taskos.online)
- 📖 [Documentation](docs/)
- 🐛 [Issue Tracker](https://github.com/caihu0916/taskforge/issues)
- 💬 [Discussions](https://github.com/caihu0916/taskforge/discussions)

---

<p align="center">
  Built with ❤ by <a href="https://github.com/caihu0916">TaskForge Team</a>
</p>
