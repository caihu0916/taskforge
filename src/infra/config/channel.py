
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""通道策略配置 + 通道配置 — 飞书/企微/钉钉凭据 + 策略"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)
from typing import Literal

from pydantic import BaseModel, Field


class ChannelPolicyConfig(BaseModel):
    """通道策略配置"""

    dm_policy: Literal["open", "allowlist", "disabled"] = Field(default="open", description="私聊策略")
    group_policy: Literal["open", "allowlist", "disabled"] = Field(default="open", description="群聊策略")
    allow_from: list[str] = Field(default_factory=list, description="访问白名单 (用户ID/群ID)")
    require_mention: bool = Field(default=False, description="群聊中是否需要@机器人才响应")
    bot_prefix: str = Field(default="", description="消息前缀触发 (如 '/')")
    filter_tool_messages: bool = Field(default=False, description="过滤工具调用输出")
    filter_thinking: bool = Field(default=False, description="过滤思考链输出")


class ChannelConfig(BaseModel):
    """通道配置 — 飞书/企微/钉钉凭据 + 策略"""

    # ── 全局默认策略 ──
    default_policy: ChannelPolicyConfig = Field(default_factory=ChannelPolicyConfig)
    # 飞书
    feishu_app_id: str = Field(default="", description="飞书 App ID")
    feishu_app_secret: str = Field(default="", description="飞书 App Secret")
    feishu_verification_token: str = Field(default="", description="飞书 Verification Token")
    feishu_encrypt_key: str = Field(default="", description="飞书 Encrypt Key")
    feishu_domain: Literal["feishu", "lark"] = Field(default="feishu", description="飞书域名: feishu/lark")
    feishu_streaming_enabled: bool = Field(
        default=True,
        description="飞书流式输出 (边生成边发送，CardKit API 失败自动降级)",
    )
    feishu_auto_task_intent: bool = Field(
        default=False,
        description="飞书自动识别任务意图 (从消息中提取任务)",
    )
    feishu_policy: ChannelPolicyConfig = Field(default_factory=ChannelPolicyConfig)

    # ── 企业微信 ──
    wechat_work_corp_id: str = Field(default="", description="企微 Corp ID")
    wechat_work_secret: str = Field(default="", description="企微 Secret")
    wechat_work_agent_id: str = Field(default="", description="企微 Agent ID")
    wechat_work_token: str = Field(default="", description="企微 Token")
    wechat_work_encoding_aes_key: str = Field(default="", description="企微 EncodingAESKey")
    wechat_work_share_session_in_group: bool = Field(
        default=False,
        description="群聊中共享会话 (同一群共上下文)",
    )
    wechat_work_streaming_enabled: bool = Field(
        default=False,
        description="企微流式输出",
    )
    wechat_policy: ChannelPolicyConfig = Field(default_factory=ChannelPolicyConfig)

    # ── 钉钉 ──
    dingtalk_app_key: str = Field(default="", description="钉钉 App Key")
    dingtalk_app_secret: str = Field(default="", description="钉钉 App Secret")
    dingtalk_agent_id: str = Field(default="", description="钉钉 Agent ID")
    dingtalk_token: str = Field(default="", description="钉钉 Token")
    dingtalk_message_type: Literal["markdown", "card"] = Field(
        default="markdown",
        description="钉钉消息类型: markdown / card",
    )
    dingtalk_card_template_id: str = Field(
        default="",
        description="钉钉卡片模板ID (message_type=card时使用)",
    )
    dingtalk_streaming_enabled: bool = Field(
        default=False,
        description="钉钉流式输出",
    )
    dingtalk_policy: ChannelPolicyConfig = Field(default_factory=ChannelPolicyConfig)

    # ── 通知 Webhook URL (用于 butler 通知广播) ──
    wechat_work_webhook_url: str = Field(
        default="", description="企业微信群机器人 Webhook URL (TF_CHANNELS__WECHAT_WORK_WEBHOOK_URL)"
    )
    wechat_work_webhook_secret: str = Field(
        default="", description="企微 Webhook 签名密钥 (TF_CHANNELS__WECHAT_WORK_WEBHOOK_SECRET)"
    )
    feishu_webhook_url: str = Field(
        default="", description="飞书自定义机器人 Webhook URL (TF_CHANNELS__FEISHU_WEBHOOK_URL)"
    )
    feishu_webhook_secret: str = Field(
        default="", description="飞书 Webhook 签名密钥 (TF_CHANNELS__FEISHU_WEBHOOK_SECRET)"
    )

    def is_feishu_configured(self) -> bool:
        return bool(self.feishu_app_id and self.feishu_app_secret)

    def is_wechat_configured(self) -> bool:
        return bool(self.wechat_work_corp_id and self.wechat_work_secret)

    def is_dingtalk_configured(self) -> bool:
        return bool(self.dingtalk_app_key and self.dingtalk_app_secret)

    def is_wechat_webhook_configured(self) -> bool:
        return bool(self.wechat_work_webhook_url)

    def is_feishu_webhook_configured(self) -> bool:
        return bool(self.feishu_webhook_url)

    def get_policy(self, channel: str) -> ChannelPolicyConfig:
        """获取通道策略, 优先级: 持久化文件 > Settings配置 > 默认策略"""
        # 基础策略
        policy_map = {
            "feishu": self.feishu_policy,
            "wechat": self.wechat_policy,
            "dingtalk": self.dingtalk_policy,
        }
        policy = policy_map.get(channel)
        base = policy if policy and policy.allow_from else self.default_policy

        # 合并持久化文件覆盖（secrets/builtin/{channel}_policy.json）
        try:
            from src.engine.channel.secrets import load_channel_policy

            saved = load_channel_policy(channel)
        except Exception as exc:
            logger.debug("exception_handled", error=str(exc))
            saved = None

        if not saved:
            return base

        # 文件字段覆盖Settings字段
        return ChannelPolicyConfig(
            dm_policy=saved.get("dm_policy", base.dm_policy),
            group_policy=saved.get("group_policy", base.group_policy),
            allow_from=saved.get("allow_from", base.allow_from),
            require_mention=saved.get("require_mention", base.require_mention),
            bot_prefix=saved.get("bot_prefix", base.bot_prefix),
            filter_tool_messages=saved.get("filter_tool_messages", base.filter_tool_messages),
            filter_thinking=saved.get("filter_thinking", base.filter_thinking),
        )
