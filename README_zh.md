---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: '976986ff-129c-4eab-b6c8-67a4924071e9'
  PropagateID: '976986ff-129c-4eab-b6c8-67a4924071e9'
  ReservedCode1: 'f9052ee9-f2c8-40d0-8fcc-05042f3683dc'
  ReservedCode2: 'f9052ee9-f2c8-40d0-8fcc-05042f3683dc'
---

# TaskForge 开源版

> AI 一人公司操作系统 — 半开源版本地优先, AI 执行, 人类拍板

[English](README.md) | [中文](README_zh.md)

## 特性

- **双模式 LLM**: 本地 (Ollama, 免费) 或远程 (SaaS API Key)
- **Agent 框架**: 12+ 角色, PDCA 流水线, A2A 协议
- **工作流 DSL**: `agent() / parallel() / pipeline() / phase() / if_else() / loop() / switch()`
- **模板市场**: 5 个示例模板 (财务/CRM/内容/办公/复盘)
- **Tauri 桌面**: 通过 `TF_DESKTOP_MODE` 环境变量切换本地/远程模式
- **零配置**: Agnes AI 预置 Key 实现开箱即用

## 快速开始

### 1. 后端 (Python 3.11+)

```bash
pip install -e ".[dev]"
python app.py  # http://localhost:8001
```

### 2. 前端 (Node 18+)

```bash
cd web
npm install
npm run dev  # http://localhost:3000
```

### 3. 启用 LLM (二选一)

**方式 A: 本地 Ollama (免费, 推荐)**

```bash
# 安装: https://ollama.com/download
ollama pull qwen2.5:7b
```

**方式 B: 远程 SaaS API Key**

```bash
python -c "import asyncio; \
  from src.infra.remote_stubs import remote_auth_login; \
  asyncio.run(remote_auth_login('you@example.com', 'password'))"
```

### 4. 运行示例场景

```bash
python examples/scenes/finance_report_demo.py
```

## 架构

```
┌─────────────────────────────────────────────┐
│  路由层 (FastAPI)                            │
├─────────────────────────────────────────────┤
│  引擎层 (Agent / LLM / Workflow / Template)  │
├─────────────────────────────────────────────┤
│  基础设施 (Config / Auth / SecureStorage)    │
└─────────────────────────────────────────────┘
```

详见 [docs/architecture.md](docs/architecture.md)。

## 开发

```bash
# 后端
ruff check src/ tests/ && ruff format
pytest tests/unit/ -v --noconftest -p no:cacheprovider

# 前端
cd web && npx tsc --noEmit && npx vite build
```

## 许可证

BSL 1.1 — 3 年非竞争期后自动转 Apache-2.0。

## 链接

- [SaaS 平台](https://cloud.taskos.online)
- [文档](docs/)
- [问题追踪](https://github.com/caihu0916/taskforge/issues)
- [桌面下载](https://github.com/caihu0916/taskforge/releases)

> AI生成