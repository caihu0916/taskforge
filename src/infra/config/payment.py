
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""支付配置 — 微信/支付宝/Stripe"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PaymentConfig(BaseModel):
    """支付配置 — 微信/支付宝/Stripe"""

    wechat_app_id: str = Field(default="", description="微信支付 AppID")
    wechat_mch_id: str = Field(default="", description="微信支付 商户号")
    wechat_api_key: str = Field(default="", description="微信支付 V3 API密钥")
    wechat_cert_path: str = Field(default="", description="微信支付 证书路径")
    wechat_notify_url: str = Field(default="", description="微信支付 回调URL")
    alipay_app_id: str = Field(default="", description="支付宝 AppID")
    alipay_private_key: str = Field(default="", description="支付宝 应用私钥")
    alipay_public_key: str = Field(default="", description="支付宝 支付宝公钥")
    alipay_notify_url: str = Field(default="", description="支付宝 回调URL")
    alipay_sandbox: bool = Field(default=True, description="支付宝 沙箱模式")
    stripe_api_key: str = Field(default="", description="Stripe Secret Key")
    stripe_webhook_secret: str = Field(default="", description="Stripe Webhook Secret")
    stripe_publishable_key: str = Field(default="", description="Stripe Publishable Key")
    app_base_url: str = Field(default="http://localhost:5173", description="前端Base URL")
    # AUTH-005: 沙箱回调验签旁路开关 — 仅非生产 + 显式启用时允许跳过签名校验 (默认 False fail-closed)
    allow_sandbox_callback: bool = Field(
        default=False,
        description="允许沙箱模式跳过回调验签(仅非生产环境,默认False;生产环境强制验签)",
    )

    def is_wechat_configured(self) -> bool:
        return bool(self.wechat_app_id and self.wechat_mch_id and self.wechat_api_key)

    def is_alipay_configured(self) -> bool:
        return bool(self.alipay_app_id and self.alipay_private_key)

    def is_stripe_configured(self) -> bool:
        return bool(self.stripe_api_key and self.stripe_api_key.startswith("sk_"))
