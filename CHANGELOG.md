# Changelog

All notable changes to this project will be documented in this file.

## [0.1.0] - 2026-07-15

### Added
- **30+ Agent Roles** — Core (PM, Developer, Designer, QA, Analyst, Writer, Researcher), Business (Finance, Legal, Marketing, Sales, HR, Operations), Code (Backend, Frontend, DevOps, Data Engineer)
- **Workflow DSL** — `agent()`, `parallel()`, `pipeline()`, `phase()`, `if_else()`, `loop()`, `switch()` primitives
- **Dual-Mode LLM** — Local (Ollama) and Remote (SaaS API) routing with 20+ provider support
- **Template Market** — 5 example templates: finance report, CRM follow-up, content calendar, meeting summary, weekly review
- **Tauri Desktop** — Cross-platform desktop app for Windows, macOS, and Linux
- **A2A Protocol** — Agent-to-Agent interoperability for distributed workflows
- **Open Source Edition** — Core engine, LLM routing, workflow compiler, template system
- **BSL 1.1 License** — Converts to Apache 2.0 on 2029-06-22

### Infrastructure
- FastAPI backend with 2000+ REST endpoints
- React 19 + TypeScript + Vite frontend
- SQLite (dev) / PostgreSQL (prod) database support
- Alembic migrations
- Structured logging with structlog
- Rate limiting and account lockout security
