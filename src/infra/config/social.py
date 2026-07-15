
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""社交平台统一配置 — 替代各 publisher 中散落的 os.getenv"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SocialConfig(BaseModel):
    """社交平台统一配置 — 替代各 publisher 中散落的 os.getenv"""

    # 抖音
    douyin_client_key: str = Field(default="", description="抖音开放平台 ClientKey")
    douyin_client_secret: str = Field(default="", description="抖音开放平台 ClientSecret")
    douyin_access_token: str = Field(default="", description="抖音 OAuth2 access_token")
    # B站
    bilibili_app_id: str = Field(default="", description="B站开放平台 AppID")
    bilibili_app_secret: str = Field(default="", description="B站开放平台 AppSecret")
    bilibili_access_token: str = Field(default="", description="B站 OAuth2 access_token")
    # 微博
    weibo_app_key: str = Field(default="", description="微博开放平台 AppKey")
    weibo_app_secret: str = Field(default="", description="微博开放平台 AppSecret")
    weibo_access_token: str = Field(default="", description="微博 OAuth2 access_token")
    # 微信公众号
    wechat_app_id: str = Field(default="", description="微信公众号 AppID")
    wechat_app_secret: str = Field(default="", description="微信公众号 AppSecret")
