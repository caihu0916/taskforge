
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""TaskForge (开源版) 统一配置入口 — re-export 层

铁律: 这是唯一的配置入口，零散的 os.getenv 在这里终结。
所有配置类实际定义在 src/infra/config/ 子模块中。
"""
from src.infra.config.settings import Settings, get_settings, reset_settings

__all__ = ["Settings", "get_settings", "reset_settings"]
