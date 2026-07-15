
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""合同电子签名配置"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DocuSignConfig(BaseModel):
    """DocuSign 电子签名配置"""

    integration_key: str = Field(default="", description="DocuSign Client ID (TF_CONTRACT__DOCUSIGN__INTEGRATION_KEY)")
    user_id: str = Field(default="", description="发送者用户 GUID (TF_CONTRACT__DOCUSIGN__USER_ID)")
    private_key: str = Field(default="", description="RSA 私钥 PEM (TF_CONTRACT__DOCUSIGN__PRIVATE_KEY)")
    base_url: str = Field(default="https://demo.docusign.net/restapi", description="DocuSign API 基地址")
    account_id: str = Field(default="", description="Account GUID (TF_CONTRACT__DOCUSIGN__ACCOUNT_ID)")

    def is_configured(self) -> bool:
        return bool(self.integration_key and self.user_id and self.private_key and self.account_id)


class FadadaConfig(BaseModel):
    """法大大电子签名配置"""

    app_id: str = Field(default="", description="法大大 App ID (TF_CONTRACT__FADADA__APP_ID)")
    app_secret: str = Field(default="", description="法大大 App Secret (TF_CONTRACT__FADADA__APP_SECRET)")
    base_url: str = Field(default="https://openapi.fadada.com/api", description="法大大 API 基地址")

    def is_configured(self) -> bool:
        return bool(self.app_id and self.app_secret)


class EsignConfig(BaseModel):
    """e签宝电子签名配置"""

    app_id: str = Field(default="", description="e签宝 App ID (TF_CONTRACT__ESIGN__APP_ID)")
    app_secret: str = Field(default="", description="e签宝 App Secret (TF_CONTRACT__ESIGN__APP_SECRET)")
    base_url: str = Field(default="https://smlopenapi.esign.cn", description="e签宝 API 基地址")

    def is_configured(self) -> bool:
        return bool(self.app_id and self.app_secret)


class AdobeSignConfig(BaseModel):
    """Adobe Acrobat Sign 电子签名配置"""

    integration_key: str = Field(
        default="", description="Adobe Sign Client ID (TF_CONTRACT__ADOBE_SIGN__INTEGRATION_KEY)"
    )
    access_token: str = Field(
        default="", description="Adobe Sign OAuth Access Token (TF_CONTRACT__ADOBE_SIGN__ACCESS_TOKEN)"
    )
    base_url: str = Field(default="https://api.adobesign.com/api/rest/v6", description="Adobe Sign API 基地址")

    def is_configured(self) -> bool:
        return bool(self.integration_key and self.access_token)


class ContractConfig(BaseModel):
    """合同电子签名配置"""

    webhook_secret: str = Field(default="", description="Webhook HMAC-SHA256签名密钥 (TF_CONTRACT__WEBHOOK_SECRET)")
    max_callback_age_seconds: int = Field(default=300, ge=60, description="回调时间戳最大容许偏差(秒)")
    docusign: DocuSignConfig = Field(default_factory=DocuSignConfig)
    adobe_sign: AdobeSignConfig = Field(default_factory=AdobeSignConfig)
    fadada: FadadaConfig = Field(default_factory=FadadaConfig)
    esign: EsignConfig = Field(default_factory=EsignConfig)
