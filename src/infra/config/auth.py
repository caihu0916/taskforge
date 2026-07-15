
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""认证配置"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ── 弱密钥黑名单（单一来源，auth.py 从此处导入）──
# 已知弱密钥（开发/测试用，绝不能用于生产）
WEAK_JWT_SECRETS = frozenset(
    {
        # 原 auth.py _KNOWN_WEAK_SECRETS (11 entries)
        "test-jwt-secret-at-least-32-characters-long!!",
        "change-me",
        "changeme",
        "secret",
        "secret123",
        "password",
        "taskforge",
        "jwt_secret",
        "jwt-secret",
        "your-secret-key",
        "my-secret",
        # 原 config/auth.py _WEAK_JWT_SECRETS 额外条目 (4 entries)
        "GENERATE-YOUR-OWN-SECRET",
        "change-me-in-production",
        "my-secret-key",
        "test-secret-key",
    }
)


class AuthConfig(BaseModel):
    """认证配置"""

    api_key: str = Field(default="", description="API Key (生产必填, 单 key 向后兼容)")
    # AUTH-009: 多 API key 支持 — list[str] 支持多键与轮换
    # 环境变量 TF_AUTH__API_KEYS 为 JSON 数组字符串，如 '["key1","key2"]'
    api_keys: list[str] = Field(
        default_factory=list,
        description="多 API Key 列表 (支持轮换, TF_AUTH__API_KEYS 为 JSON 数组)",
    )
    jwt_secret: str = Field(default="", description="JWT 签名密钥 (生产必填, 至少64字符); 开发环境至少32字符")
    jwt_expire_minutes: int = Field(default=60, ge=1, le=1440)
    rate_limit: int = Field(default=100, ge=1, le=10000, description="每分钟请求限制")
    rate_limit_backend: Literal["memory", "redis"] = Field(
        default="memory", description="限流后端: memory(默认) 或 redis(生产推荐)"
    )
    cors_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173,https://www.taskos.cloud,https://taskos.cloud",
        description="CORS 允许的来源(逗号分隔)",
    )
    strict_revocation_check: bool = Field(
        default=False,
        description="Redis不可用时严格拒绝已注销Token(生产True,开发可False；缺省False避免无Redis时全局401)",
    )
    allow_unauthenticated_websocket: bool = Field(
        default=False, description="允许未认证的WebSocket连接(仅开发环境使用，生产环境必须为False)"
    )
    # AUTH-002: dev 旁路显式开关 — 默认 False 拒绝；True 时仅授予 role=user (非 admin)
    allow_dev_bypass: bool = Field(
        default=False,
        description="允许开发模式旁路认证(仅非生产环境,默认False;启用时授予role=user而非admin)",
    )
    # AUTH-011: 可信代理列表 — 仅信任这些代理的 X-Forwarded-For
    # 逗号分隔，空则完全不信任 XFF (直接用 client.host)
    trusted_proxies: str = Field(
        default="",
        description="可信代理 IP 列表(逗号分隔)，仅这些代理的 XFF 被信任；空则不信任任何 XFF",
    )

    def get_all_api_keys(self) -> list[str]:
        """AUTH-009: 返回所有有效 API key (合并 api_key + api_keys)

        - 旧的单 key (api_key) 仍有效，向后兼容
        - 新的多 key (api_keys) 支持轮换
        - 去重后返回
        """
        keys: list[str] = []
        if self.api_key:
            keys.append(self.api_key)
        keys.extend(self.api_keys or [])
        # 去重保序
        seen: set[str] = set()
        unique: list[str] = []
        for k in keys:
            if k and k not in seen:
                seen.add(k)
                unique.append(k)
        return unique

    def get_trusted_proxy_list(self) -> list[str]:
        """AUTH-011: 返回可信代理 IP 列表"""
        if not self.trusted_proxies:
            return []
        return [p.strip() for p in self.trusted_proxies.split(",") if p.strip()]

    _DEV_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]
    # 生产环境允许的 CORS 来源模式（仅精确域名，不支持通配符）
    _PROD_VALID_ORIGINS = ("http://", "https://")

    def get_cors_list(self, is_production: bool = False) -> list[str]:
        """根据环境返回 CORS origins 列表

        - 生产环境: 返回 cors_origins 配置中显式定义的 origins
        - 开发环境: 仅允许 localhost 开发服务器
        """
        if is_production:
            return [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        return list(self._DEV_ORIGINS)

    def validate_cors_for_production(self) -> list[str]:
        """生产环境 CORS 校验，返回错误列表（空=通过）"""
        errors = []
        if not self.cors_origins:
            errors.append("PRODUCTION: cors_origins 未配置，生产环境必须设置有效的 CORS 来源")
            return errors

        origins = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        if not origins:
            errors.append("PRODUCTION: cors_origins 为空，生产环境必须设置有效的 CORS 来源")
            return errors

        for origin in origins:
            # 检查是否以有效协议开头
            if not origin.startswith(self._PROD_VALID_ORIGINS):
                errors.append(f"PRODUCTION: CORS 来源 '{origin}' 必须以 http:// 或 https:// 开头")
            # 检查是否包含通配符（生产环境禁止）
            if "*" in origin:
                errors.append(f"PRODUCTION: CORS 来源 '{origin}' 包含通配符 *，生产环境禁止使用通配符")
            # 检查是否是 localhost（生产环境不应使用）
            if "localhost" in origin or "127.0.0.1" in origin:
                errors.append(f"PRODUCTION: CORS 来源 '{origin}' 包含 localhost，生产环境应使用真实域名")
        return errors

    def validate_jwt_secret_for_production(self) -> None:
        if not self.jwt_secret:
            raise RuntimeError("JWT_SECRET 未配置")
        if len(self.jwt_secret) < 64:
            raise RuntimeError("JWT_SECRET 长度不足64字符（生产环境强制要求≥64字符）")
        if self.jwt_secret in WEAK_JWT_SECRETS:
            raise RuntimeError("JWT_SECRET 使用了已知弱默认值")
