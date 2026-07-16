---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: 'd3a536ed-6b4c-44e8-97ad-4c08639fe95f'
  PropagateID: 'd3a536ed-6b4c-44e8-97ad-4c08639fe95f'
  ReservedCode1: '3fa114b6-82a9-4999-9d47-75b1fc9abbe6'
  ReservedCode2: '3fa114b6-82a9-4999-9d47-75b1fc9abbe6'
---

# 安装指南

## 系统要求

| 项目 | 最低要求 | 推荐配置 |
|------|----------|----------|
| 操作系统 | Windows 10 / macOS 12 / Ubuntu 20.04 | 最新版本 |
| Python | 3.11+ | 3.12+ |
| Node.js | 18+ | 20+ |
| 内存 | 4GB | 8GB+ |
| 磁盘空间 | 1GB | 5GB+ |

## 方式一：源码安装（推荐）

### 1. 克隆项目

```bash
git clone https://github.com/caihu0916/taskforge.git
cd taskforge
```

### 2. 安装后端依赖

```bash
# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# 安装依赖
pip install -e ".[dev]"
```

### 3. 安装前端依赖

```bash
cd web
npm install
cd ..
```

### 4. 配置环境变量

```bash
# 复制示例配置
cp .env.example .env

# 编辑 .env 文件，至少配置以下变量：
# TF_AUTH__JWT_SECRET=你的JWT密钥（至少32位随机字符串）
# TF_LLM__PROVIDER=ollama
# TF_LLM__MODEL=qwen2.5:7b
```

### 5. 启动服务

```bash
# 终端1：启动后端
python app.py

# 终端2：启动前端
cd web && npm run dev
```

### 6. 访问应用

- 前端界面：http://localhost:3000
- 后端API：http://localhost:8001
- API文档：http://localhost:8001/docs

## 方式二：Docker部署

### 1. 配置环境变量

```bash
export TF_AUTH__JWT_SECRET=你的密钥
export DB_PASSWORD=数据库密码
export REDIS_PASSWORD=Redis密码
```

### 2. 启动服务

```bash
# 开发模式
docker compose up -d

# 生产模式（含Nginx + SSL）
docker compose --profile production up -d
```

### 3. 查看日志

```bash
docker compose logs -f taskforge
```

## 方式三：桌面应用（Tauri）

### 下载安装

前往 [GitHub Releases](https://github.com/caihu0916/taskforge/releases) 下载对应操作系统的安装包：

| 操作系统 | 安装包 | 说明 |
|----------|--------|------|
| Windows | `taskforge_*_x64-setup.exe` | NSIS 安装程序，双击运行 |
| macOS (Apple Silicon) | `taskforge_*_aarch64.dmg` | M1/M2/M3 芯片 |
| macOS (Intel) | `taskforge_*_x64.dmg` | Intel 芯片 |
| Linux | `taskforge_*_amd64.deb` | Debian/Ubuntu |
| Linux | `taskforge_*.AppImage` | 通用格式，无需安装 |

### 验证完整性（可选）

下载 `checksums.sha256` 文件，校验安装包完整性：

```bash
# macOS/Linux
sha256sum -c checksums.sha256

# Windows (PowerShell)
Get-FileHash taskforge_*_x64-setup.exe -Algorithm SHA256
```

### 首次启动

1. 打开 TaskForge 桌面应用
2. 注册账号或登录
3. 配置 API Key（详见 [配置说明](configuration.md)）

## 常见问题

### Q: pip install 失败怎么办？

```bash
# 升级pip
python -m pip install --upgrade pip

# 使用国内镜像
pip install -e ".[dev]" -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### Q: npm install 失败怎么办？

```bash
# 清除缓存
npm cache clean --force

# 使用国内镜像
npm config set registry https://registry.npmmirror.com
npm install
```

### Q: 端口被占用怎么办？

修改 `.env` 文件中的端口配置：
```
TF_SERVER__PORT=8002
```

## 下一步

安装完成后，请查看 [配置说明](configuration.md) 进行详细配置。

> AI生成