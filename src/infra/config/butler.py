
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Butler 助理配置 — 日历/邮件/通知"""

from __future__ import annotations

from pydantic import BaseModel, Field


class EmailSMTPConfig(BaseModel):
    """SMTP 邮件配置"""

    host: str = Field(default="", description="SMTP 服务器 (TF_BUTLER__EMAIL__SMTP__HOST)")
    port: int = Field(default=587, description="SMTP 端口 (TF_BUTLER__EMAIL__SMTP__PORT)")
    username: str = Field(default="", description="SMTP 用户名 (TF_BUTLER__EMAIL__SMTP__USERNAME)")
    password: str = Field(default="", description="SMTP 密码 (TF_BUTLER__EMAIL__SMTP__PASSWORD)")
    use_tls: bool = Field(default=True, description="启用 TLS (TF_BUTLER__EMAIL__SMTP__USE_TLS)")
    from_address: str = Field(default="", description="发件人地址 (TF_BUTLER__EMAIL__SMTP__FROM_ADDRESS)")
    from_name: str = Field(default="TaskForge", description="发件人名称 (TF_BUTLER__EMAIL__SMTP__FROM_NAME)")
    base_url: str = Field(
        default="http://localhost:3000", description="前端重置密码链接基础 URL (TF_BUTLER__EMAIL__SMTP__BASE_URL)"
    )

    def is_configured(self) -> bool:
        return bool(self.host and self.username)


class EmailMailgunConfig(BaseModel):
    """Mailgun 邮件配置"""

    api_key: str = Field(default="", description="Mailgun API Key (TF_BUTLER__EMAIL__MAILGUN__API_KEY)")
    domain: str = Field(default="", description="Mailgun 域名 (TF_BUTLER__EMAIL__MAILGUN__DOMAIN)")
    from_address: str = Field(default="", description="发件人地址 (TF_BUTLER__EMAIL__MAILGUN__FROM_ADDRESS)")

    def is_configured(self) -> bool:
        return bool(self.api_key and self.domain)


class EmailConfig(BaseModel):
    """邮件 Provider 配置"""

    provider: str = Field(default="mock", description="邮件 Provider: mock/smtp/mailgun (TF_BUTLER__EMAIL__PROVIDER)")
    smtp: EmailSMTPConfig = Field(default_factory=EmailSMTPConfig)
    mailgun: EmailMailgunConfig = Field(default_factory=EmailMailgunConfig)


class CalendarConfig(BaseModel):
    """日历 Provider 配置"""

    provider: str = Field(default="mock", description="日历 Provider: mock/ical/google (TF_BUTLER__CALENDAR__PROVIDER)")
    storage_path: str = Field(default="data/butler/calendar", description="日历存储路径")
    ics_path: str = Field(default="", description="iCal 文件路径")


class ButlerConfig(BaseModel):
    """Butler 助理配置"""

    calendar: CalendarConfig = Field(default_factory=CalendarConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
