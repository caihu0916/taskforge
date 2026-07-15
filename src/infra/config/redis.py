
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Redis 配置 (可选，生产推荐)"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RedisConfig(BaseModel):
    """Redis 配置 (可选，生产推荐)"""

    url: str = Field(default="redis://localhost:6379/0", description="Redis 连接 URL (rediss:// 启用SSL)")
    password: str = Field(default="", description="Redis 密码 (也可写在URL中)")
    max_connections: int = Field(default=20, ge=1, le=100, description="最大连接数")
    socket_timeout: float = Field(default=5.0, ge=1.0, le=30.0, description="Socket 超时(秒)")
    socket_connect_timeout: float = Field(default=5.0, ge=1.0, le=30.0, description="Socket 连接超时(秒)")
    enabled: bool = Field(default=False, description="是否启用 Redis (生产建议开启)")
    # Sentinel 高可用
    sentinel_hosts: list[str] = Field(
        default=[], description="Sentinel 地址列表 (如 ['10.0.0.1:26379','10.0.0.2:26379'])"
    )
    sentinel_master: str = Field(default="mymaster", description="Sentinel 监控的 master 名称")
    sentinel_password: str = Field(default="", description="Sentinel 自身密码 (可与Redis密码不同)")
    # SSL/TLS
    ssl: bool = Field(default=False, description="启用 SSL/TLS 加密连接 (也可用 rediss:// URL)")
    ssl_cert_reqs: str = Field(default="required", description="SSL 证书验证: required | optional | none")
    ssl_ca_certs: str = Field(default="", description="CA 证书包文件路径")
    ssl_certfile: str = Field(default="", description="客户端证书文件路径")
    ssl_keyfile: str = Field(default="", description="客户端私钥文件路径")

    @property
    def is_configured(self) -> bool:
        return bool(self.url) and self.enabled

    @property
    def is_sentinel_mode(self) -> bool:
        """是否启用 Sentinel 高可用模式"""
        return len(self.sentinel_hosts) > 0

    @property
    def is_ssl_mode(self) -> bool:
        """是否需要 SSL 连接 (显式开启或 URL 使用 rediss://)"""
        return self.ssl or self.url.startswith("rediss://")

    @property
    def ssl_params(self) -> dict:
        """构建 redis 连接所需的 SSL 参数字典"""
        if not self.is_ssl_mode:
            return {}
        import ssl as _ssl

        cert_reqs_map = {
            "required": _ssl.CERT_REQUIRED,
            "optional": _ssl.CERT_OPTIONAL,
            "none": _ssl.CERT_NONE,
        }
        params: dict = {"ssl": True, "ssl_cert_reqs": cert_reqs_map.get(self.ssl_cert_reqs, _ssl.CERT_REQUIRED)}
        if self.ssl_ca_certs:
            params["ssl_ca_certs"] = self.ssl_ca_certs
        if self.ssl_certfile:
            params["ssl_certfile"] = self.ssl_certfile
        if self.ssl_keyfile:
            params["ssl_keyfile"] = self.ssl_keyfile
        return params
