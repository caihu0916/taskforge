---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: '2fa897b4-8ea8-43f7-ae8f-e5cde282a8b9'
  PropagateID: '2fa897b4-8ea8-43f7-ae8f-e5cde282a8b9'
  ReservedCode1: '3d2edd92-daef-40fe-9ff2-70c2c3938d7f'
  ReservedCode2: '3d2edd92-daef-40fe-9ff2-70c2c3938d7f'
---

# TaskForge Open Source

> AI Agent OS for Solo Entrepreneurs — 半开源版本地优先, AI 执行, 人类拍板

[English](README.md) | [中文](README_zh.md)

## Features

- **Dual-Mode LLM**: Local (Ollama, free) or Remote (SaaS API Key)
- **Agent Framework**: 12+ roles, PDCA pipeline, A2A protocol
- **Workflow DSL**: `agent() / parallel() / pipeline() / phase() / if_else() / loop() / switch()`
- **Template Market**: 5 example templates (finance/CRM/content/office/review)
- **Tauri Desktop**: Local/Remote mode switch via `TF_DESKTOP_MODE` env
- **Zero-Config**: Agnes AI preset key for instant onboarding

## Quick Start

### 1. Backend (Python 3.11+)

```bash
pip install -e ".[dev]"
python app.py  # http://localhost:8001
```

### 2. Frontend (Node 18+)

```bash
cd web
npm install
npm run dev  # http://localhost:3000
```

### 3. Enable LLM (Choose one)

**Option A: Local Ollama (Free, Recommended)**

```bash
# Install: https://ollama.com/download
ollama pull qwen2.5:7b
```

**Option B: Remote SaaS API Key**

```bash
python -c "import asyncio; \
  from src.infra.remote_stubs import remote_auth_login; \
  asyncio.run(remote_auth_login('you@example.com', 'password'))"
```

### 4. Run Example Scene

```bash
python examples/scenes/finance_report_demo.py
```

## Architecture

```
┌─────────────────────────────────────────────┐
│  Routes (FastAPI)                           │
├─────────────────────────────────────────────┤
│  Engine (Agent / LLM / Workflow / Template) │
├─────────────────────────────────────────────┤
│  Infra (Config / Auth / SecureStorage)      │
└─────────────────────────────────────────────┘
```

See [docs/architecture.md](docs/architecture.md) for details.

## Development

```bash
# Backend
ruff check src/ tests/ && ruff format
pytest tests/unit/ -v --noconftest -p no:cacheprovider

# Frontend
cd web && npx tsc --noEmit && npx vite build
```

## License

BSL 1.1 — 3-year non-compete period, then auto-converts to Apache-2.0.

## Links

- [SaaS Platform](https://cloud.taskos.online)
- [Documentation](docs/)
- [Issue Tracker](https://github.com/caihu0916/taskforge/issues)
- [Desktop Downloads](https://github.com/caihu0916/taskforge/releases)

> AI生成