
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""服务器配置 + Obsidian + 图片生成"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path  # noqa: TC003
from typing import Literal

from pydantic import BaseModel, Field

from src.infra.config._constants import PROJECT_ROOT

# ponytail: 跨平台推导, Linux=tempfile.gettempdir()=/tmp, Windows=%TEMP%.
# 原默认 /tmp/taskforge_metrics 在 Windows 上 PermissionError (拒绝访问), 影响约 90 个集成测试.
_PROMETHEUS_METRICS_DEFAULT = os.path.join(tempfile.gettempdir(), "taskforge_metrics")


class ServerConfig(BaseModel):
    """服务器配置"""

    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8001, ge=1, le=65535)
    workers: int = Field(default=1, ge=1, le=16)
    reload: bool = Field(default=False)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")
    log_format: Literal["json", "console"] = Field(default="console")
    environment: Literal["development", "staging", "production", "testing", "test"] = Field(default="development")
    data_dir: Path = Field(default=PROJECT_ROOT / "data")
    observability_dir: Path = Field(
        default=PROJECT_ROOT / "data" / "observability", description="JSONL可观测性日志目录"
    )
    encryption_key: str | None = Field(default=None, description="Fernet对称加密密钥(TF_ENCRYPTION_KEY)")
    allow_plaintext_fallback: bool = Field(default=False, description="允许Base64降级存储API Key(仅开发)")
    media_dir: str = Field(default="", description="媒体文件存储目录 (TF_SERVER__MEDIA_DIR)")
    sandbox_tmp_dir: str = Field(default="", description="代码沙箱临时目录 (TF_SANDBOX_TMP_DIR)")
    search_url: str = Field(default="", description="搜索引擎地址 (TF_SEARCH_URL)")
    sentry_dsn: str = Field(default="", description="Sentry DSN (TF_SENTRY_DSN)")
    loki_url: str = Field(default="", description="Loki push URL (TF_SERVER__LOKI_URL)")
    sentry_environment: str = Field(default="", description="Sentry environment (覆盖server.environment)")
    sentry_release: str = Field(default="", description="Sentry release (TF_VERSION)")
    docs_root: str = Field(default="", description="文档输出根目录(TF_DOCS_ROOT)，空则用PROJECT_ROOT/docs")
    allowed_dirs: str = Field(default="", description="文件工具允许目录，逗号分隔(TF_ALLOWED_DIRS)，空则自动推导")
    baidu_ocr_api_key: str = Field(default="", description="百度OCR API Key (TF_SERVER__BAIDU_OCR_API_KEY)")
    baidu_ocr_secret_key: str = Field(default="", description="百度OCR Secret Key (TF_SERVER__BAIDU_OCR_SECRET_KEY)")
    managed_skills_dir: str = Field(default="", description="托管技能目录 (TF_SERVER__MANAGED_SKILLS_DIR)")
    prometheus_multiproc_dir: str = Field(
        default=_PROMETHEUS_METRICS_DEFAULT,
        description="Prometheus多进程指标目录 (TF_SERVER__PROMETHEUS_MULTIPROC_DIR)",
    )
    transformers_offline: bool = Field(
        default=True, description="HuggingFace Transformers离线模式 (TF_SERVER__TRANSFORMERS_OFFLINE)"
    )
    otlp_endpoint: str = Field(
        default="",
        description="OpenTelemetry OTLP Collector gRPC地址 (TF_SERVER__OTLP_ENDPOINT)，空则读OS环境变量OTEL_EXPORTER_OTLP_ENDPOINT",
    )
    font_dirs: str = Field(
        default="", description="自定义字体目录，逗号分隔 (TF_SERVER__FONT_DIRS)，空则自动检测系统字体"
    )
    health_cache_ttl: float = Field(
        default=5.0, ge=1.0, le=60.0, description="健康检查缓存TTL(秒)，减少频繁的DB/Redis连接测试"
    )
    max_thread_workers: int = Field(
        default_factory=lambda: min(32, (os.cpu_count() or 1) * 5),
        ge=1,
        le=32,
        description="ThreadPoolExecutor最大线程数(I/O密集型标准: CPU*5，上限32) (TF_SERVER__MAX_THREAD_WORKERS)",
    )


class ObsidianConfig(BaseModel):
    """Obsidian Vault 配置"""

    vault_path: str = Field(default="", description="Obsidian Vault 路径 (TF_OBSIDIAN__VAULT_PATH)")
    config_dir: str = Field(
        default="", description="Obsidian配置目录 (TF_OBSIDIAN__CONFIG_DIR)，空则自动检测(%APPDATA%/obsidian)"
    )
    auto_sync: bool = Field(default=False, description="自动同步到 Vault")
    sync_interval: int = Field(default=300, ge=30, description="同步间隔(秒)")
    note_template: str = Field(default="default", description="笔记模板名")
    ignore_patterns: list[str] = Field(
        default=[".obsidian/**", ".trash/**", ".templates/**", "*.excalidraw*"],
        description="忽略的文件模式 (glob)",
    )


class ImageGenConfig(BaseModel):
    """图片生成 API 配置"""

    provider: str = Field(default="", description="图片生成服务商: openai/stability/flux，空则仅生成文本prompt")
    api_key: str = Field(default="", description="API密钥 (TF_IMAGE_GEN__API_KEY)")
    base_url: str = Field(default="", description="自定义API端点 (TF_IMAGE_GEN__BASE_URL)")
    model: str = Field(default="dall-e-3", description="模型名: dall-e-3/stable-diffusion-xl/flux-pro")
