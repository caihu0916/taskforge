
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""计费配置 — 收款码付费模式"""

from __future__ import annotations

from pydantic import BaseModel, Field


class BillingConfig(BaseModel):
    """计费配置 — 收款码付费模式"""

    enabled: bool = Field(default=False, description="启用计费拦截（生产建议开启）")
    wechat_qr: str = Field(default="", description="微信收款码URL")
    alipay_qr: str = Field(default="", description="支付宝收款码URL")
    contact: str = Field(default="联系客服确认付款", description="付款联系提示")
    note_prefix: str = Field(default="TF", description="付款备注前缀")
    usd_cny_rate: float = Field(default=7.2, description="USD→CNY汇率")
    min_balance: float = Field(default=0.01, description="允许调用的最低余额（元）")
