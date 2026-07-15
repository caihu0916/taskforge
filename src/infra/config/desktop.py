
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Electron 桌面壳层配置"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DesktopConfig(BaseModel):
    """Electron 桌面壳层配置"""

    tray_enabled: bool = Field(default=True, description="系统托盘启用 (TF_DESKTOP__TRAY_ENABLED)")
    auto_start: bool = Field(default=False, description="开机自启 (TF_DESKTOP__AUTO_START)")
    notifications_enabled: bool = Field(default=True, description="原生通知 (TF_DESKTOP__NOTIFICATIONS_ENABLED)")
    minimize_to_tray: bool = Field(default=True, description="最小化到托盘 (TF_DESKTOP__MINIMIZE_TO_TRAY)")
    desktop_client: bool = Field(default=False, description="Electron桌面客户端检测 (TF_DESKTOP_CLIENT)")
    desktop_version: str = Field(default="", description="Electron桌面客户端版本 (TF_DESKTOP_VERSION)")
