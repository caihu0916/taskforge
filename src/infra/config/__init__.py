
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""配置模块 — 所有配置类拆分到子模块，此处统一 re-export

新代码直接从此模块导入:
    from src.infra.config import Settings, get_settings, DatabaseConfig, ...

向后兼容: 根目录 config.py 仍可正常 import (re-export 自此模块)。
"""

# ── 常量和工具 ──
from __future__ import annotations

from src.infra.config._constants import PROJECT_ROOT
from src.infra.config.auth import AuthConfig
from src.infra.config.billing import BillingConfig
from src.infra.config.bridge import BridgeConfig
from src.infra.config.browser import BrowserConfig
from src.infra.config.channel import ChannelConfig, ChannelPolicyConfig
from src.infra.config.code_execution import CodeExecutionConfig
from src.infra.config.contract import ContractConfig
from src.infra.config.credential_pool import CredentialPoolConfig

# ── 配置类 (按领域拆分的子模块) ──
from src.infra.config.database import DatabaseConfig
from src.infra.config.delegate import DelegateConfig
from src.infra.config.desktop import DesktopConfig
from src.infra.config.gateway import GatewayConfig
from src.infra.config.llm import LLMConfig
from src.infra.config.memory import MemoryConfig
from src.infra.config.payment import PaymentConfig
from src.infra.config.persistence import persist_env
from src.infra.config.redis import RedisConfig
from src.infra.config.security import BashSecurityConfig, SecurityConfig
from src.infra.config.server import ImageGenConfig, ObsidianConfig, ServerConfig

# ── 主 Settings 类 + 单例 + 工具函数 ──
from src.infra.config.settings import Settings, get_settings, load_hermes_config, reset_settings
from src.infra.config.social import SocialConfig
from src.infra.config.task import TaskConfig
from src.infra.config.terminal import TerminalConfig
from src.infra.config.upload import UploadConfig
from src.infra.config.watermark import WatermarkConfig
from src.infra.config.ws import WSConfig

__all__ = [
    # Constants
    "PROJECT_ROOT",
    "AuthConfig",
    "BashSecurityConfig",
    "BillingConfig",
    "BridgeConfig",
    "BrowserConfig",
    "ChannelConfig",
    "ChannelPolicyConfig",
    "CodeExecutionConfig",
    "ContractConfig",
    "CredentialPoolConfig",
    # Config models
    "DatabaseConfig",
    "DelegateConfig",
    "DesktopConfig",
    "GatewayConfig",
    "ImageGenConfig",
    "LLMConfig",
    "MemoryConfig",
    "ObsidianConfig",
    "PaymentConfig",
    "RedisConfig",
    "SecurityConfig",
    "ServerConfig",
    # Settings & helpers
    "Settings",
    "SocialConfig",
    "TaskConfig",
    "TerminalConfig",
    "UploadConfig",
    "WSConfig",
    "WatermarkConfig",
    "get_settings",
    "load_hermes_config",
    "persist_env",
    "reset_settings",
]
