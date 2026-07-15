# TaskForge 开源版架构

## 四层架构

```
┌─────────────────────────────────────────────────────────┐
│  路由层  src/api/                                        │
│  职责: 参数校验 → 调用引擎 → 格式化响应                    │
│  铁律: 路由不写业务逻辑                                    │
├─────────────────────────────────────────────────────────┤
│  引擎层  src/engine/                                     │
│  ├─ agent/   Agent Pipeline + 角色系统 + A2A             │
│  ├─ llm/     LLMRouter 双模式 + OllamaProvider           │
│  ├─ workflow/ PDCA DSL + 事件溯源                        │
│  ├─ tool/    工具注册中心                                 │
│  └─ template_market/ 模板管理                            │
│  职责: 核心业务逻辑, 不直接处理 HTTP                       │
├─────────────────────────────────────────────────────────┤
│  基础设施层  src/infra/                                   │
│  ├─ auth/      JWT + bcrypt + 中间件                     │
│  ├─ config/    Settings + 唯一配置源                     │
│  ├─ database/  ConnectionManager + BaseManager           │
│  ├─ startup/   app_factory + welcome 引导                │
│  └─ secure_storage.py  API Key 加密存储                  │
│  职责: 技术基础设施, 不含业务语义                          │
└─────────────────────────────────────────────────────────┘
```

## LLM 双模式路由

开源版核心创新: 本地/远程双模式自动分发。

```
LLMRouter.chat()
    │
    ▼
_detect_mode()
    │
    ├── Ollama 可用 → "local" → OllamaProvider.chat()
    │                             ↓
    │                             httpx → localhost:11434
    │
    ├── 有 API Key → "remote" → remote_llm_chat()
    │                             ↓
    │                             httpx → SaaS /api/v1/llm/chat
    │
    └── 两者均无 → "unavailable" → RuntimeError 含注册引导
```

### 模式优先级

1. **local** — Ollama 可用时优先 (免费、隐私)
2. **remote** — 有 API Key 时使用 SaaS (付费、强大)
3. **unavailable** — 两者均不可用时抛异常含引导

### 关键文件

| 文件 | 职责 |
|------|------|
| `src/engine/llm/_router_core.py` | LLMRouter 双模式桩版本 |
| `src/engine/llm/_local_provider.py` | OllamaProvider 本地实现 |
| `src/infra/remote_stubs.py` | SaaS 远程桩函数 (6个) |
| `src/infra/secure_storage.py` | API Key 加密存储 |
| `src/infra/config/remote.py` | RemoteConfig (base_url/timeout) |

## 配置系统

唯一配置入口: `from config import get_settings`

### 环境变量

| 变量 | 用途 | 默认值 |
|------|------|--------|
| `TF_LLM__BASE_URL` | LLM Provider URL | http://localhost:11434 |
| `TF_LLM__MODEL` | 默认模型 | (空) |
| `TF_REMOTE__BASE_URL` | SaaS 服务端 URL | https://api.taskforge.cn |
| `TF_REMOTE__TIMEOUT` | HTTP 超时秒数 | 30 |
| `TF_SERVER__ENCRYPTION_KEY` | 加密密钥 (Fernet) | (启动时校验) |
| `TF_DESKTOP_MODE` | Tauri 桌面模式 | local |

## 前端架构

```
web/src/
├── lib/api.ts          # ky 单例, env 驱动 API_BASE
├── stores/auth.ts      # Zustand 认证状态
├── services/           # API 服务层
└── pages/              # React 页面
```

### 双模式 API 配置

```typescript
// 不设 env → 本地模式
const API_BASE = "/api/v1"

// 设 env → 远程模式
VITE_API_BASE_URL=https://api.taskforge.cn/api/v1
```

## Tauri 桌面双模式

```rust
// TF_DESKTOP_MODE=local (默认) → 启动 Python sidecar
// TF_DESKTOP_MODE=remote → 前端直连 SaaS API
pub fn read_backend_mode() -> BackendMode
```

### CSP 动态化

- Local 模式: `connect-src 'self' http://localhost:* http://127.0.0.1:*`
- Remote 模式: `connect-src 'self' https://*.taskforge.cn`

## 测试

```bash
# 全量测试 (67 测试)
pytest tests/unit/ -v --noconftest -p no:cacheprovider

# 单模块
pytest tests/unit/test_local_provider.py -v
pytest tests/unit/test_router_core_stub.py -v
pytest tests/unit/test_remote_stubs.py -v
pytest tests/unit/test_app_factory.py -v
```

## 模块依赖矩阵

| 模块 | 依赖 |
|------|------|
| `_router_core` | `_local_provider`, `remote_stubs`, `secure_storage` |
| `_local_provider` | `config`, `httpx`, `structlog` |
| `remote_stubs` | `secure_storage`, `config`, `httpx`, `structlog` |
| `app_factory` | `fastapi`, `structlog` |
| `welcome` | `_router_core`, `structlog` |
