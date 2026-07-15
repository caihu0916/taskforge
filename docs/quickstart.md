# TaskForge 开源版快速开始

## 前置条件

- Python 3.11+
- Node.js 18+
- (可选) Ollama — 本地 LLM
- (可选) Tauri CLI — 桌面打包

## 5 分钟 Hello World

### 1. 克隆并安装

```bash
git clone https://github.com/taskforge/taskforge.git
cd taskforge/open
pip install -e ".[dev]"
```

### 2. 启动后端

```bash
python app.py
# 输出: TaskForge Open Source starting...
#       welcome_shown mode=unavailable (或 local/remote)
```

### 3. 启用 LLM (二选一)

#### 方式 A: 本地 Ollama (免费)

```bash
# 安装 Ollama: https://ollama.com/download
ollama pull qwen2.5:7b

# 验证
python -c "import asyncio; \
  from src.engine.llm._local_provider import OllamaProvider; \
  print(asyncio.run(OllamaProvider().is_available()))"
# 输出: True
```

#### 方式 B: 远程 SaaS API Key

```bash
# 注册: https://taskforge.cn/register
python -c "import asyncio; \
  from src.infra.remote_stubs import remote_auth_login; \
  print(asyncio.run(remote_auth_login('you@example.com', 'password')))"
# 输出: sk-xxxxx...
```

### 4. 运行示例场景

```bash
python examples/scenes/finance_report_demo.py
```

预期输出:
```
[模式检测] 当前 LLM 模式: local
[调用] 使用 local 模式生成财务报表...
============================================================
生成的财务报表:
# 2026年7月财务报表
...
```

### 5. 启动前端 (开发模式)

```bash
cd web
npm install
npm run dev
# 访问 http://localhost:3000
```

## 桌面版打包 (Tauri)

### Local 模式 (默认)

```bash
cd src-tauri
cargo build --release
# 启动后自动拉起 Python sidecar
```

### Remote 模式

```bash
# 设置环境变量
export TF_DESKTOP_MODE=remote
cd src-tauri
cargo build --release
# 启动后前端直连 SaaS API, 无需 Python
```

## 常见问题

### Q: 启动后显示 "无可用 LLM"

A: 未安装 Ollama 也未配置 API Key。按上方"启用 LLM"步骤操作。

### Q: Ollama 调用超时

A: 检查 Ollama 服务是否运行: `curl http://localhost:11434/api/tags`

### Q: API Key 配置后仍提示 unavailable

A: 检查 secure_storage 是否可写入: `~/.taskforge/` 目录权限。

### Q: 前端构建报错 `import.meta.env`

A: 确认 `web/src/vite-env.d.ts` 存在且 Vite 版本 >= 5。

## 下一步

- 阅读 [架构文档](architecture.md) 了解四层架构
- 查看 [示例模板](../examples/templates/) 学习 PDCA 工作流
- 运行 [示例场景](../examples/scenes/) 体验完整流程
