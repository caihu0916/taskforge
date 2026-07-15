
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""TaskForge 认证模块 — API Key + JWT 双模式

设计决策:
  - 开发模式: API Key 或无认证 (TF_AUTH__API_KEY 为空时可配置放行)
  - 生产模式: API Key 或 JWT 必须通过一个
  - JWT 签名密钥从 TF_AUTH__JWT_SECRET 读取
  - 零裸 os.environ/getenv，统一走 Settings
  - 用 FastAPI Depends 而非 BaseHTTPMiddleware (避免流式响应 bug)
  - Token 黑名单存储于 Redis，支持即时注销

铁律: 认证中间件从第一行代码就开，零注释掉的中间件。
"""

from __future__ import annotations

import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import jwt
import structlog
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from config import get_settings
from src.exceptions import AuthError
from src.infra.config.auth import WEAK_JWT_SECRETS as _KNOWN_WEAK_SECRETS

logger = structlog.get_logger(__name__)

# ── Token 黑名单配置 ──

_TOKEN_BLACKLIST_PREFIX = "jwt:blacklist:"
_TOKEN_BLACKLIST_TTL = 3600 * 24 * 7  # 7天过期（覆盖最长JWT有效期）

# ── 弱密钥检测 ──

# 弱密钥黑名单从 config/auth.py 统一导入（单一来源，P1-1）
# 弱密钥模式：全小写/全数字、过短(<32字符)、包含test/dev/change-me等
_WEAK_SECRET_PATTERNS = re.compile(
    r"(?i)^(test|dev|change|demo|example|placeholder|default|sample)",
)


def _is_weak_jwt_secret(secret: str, is_production: bool = False) -> tuple[bool, str]:
    """检测JWT密钥是否为弱密钥，返回 (is_weak, reason)

    生产环境强制要求≥64字符（512bit），开发环境≥32字符。
    """
    if secret in _KNOWN_WEAK_SECRETS:
        return True, "known weak secret"
    min_length = 64 if is_production else 32
    if len(secret) < min_length:
        return (
            True,
            f"too short ({len(secret)} chars, minimum {min_length} for {'production' if is_production else 'development'})",
        )
    if _WEAK_SECRET_PATTERNS.match(secret):
        return True, f"matches weak pattern: {_WEAK_SECRET_PATTERNS.match(secret).group()!r}"
    return False, ""


def validate_jwt_secret_on_startup() -> None:
    """启动时检测JWT密钥强度。生产环境遇到弱密钥拒绝启动。"""
    settings = get_settings()
    secret = settings.auth.jwt_secret
    is_prod = settings.is_production()
    if not secret:
        if is_prod:
            raise RuntimeError("FATAL: JWT_SECRET is empty in production. Refusing to start.")
        logger.warning("jwt_secret_not_configured", hint="Set TF_AUTH__JWT_SECRET for security")
        return

    is_weak, reason = _is_weak_jwt_secret(secret, is_production=is_prod)
    if is_weak:
        if is_prod:
            raise RuntimeError(
                f"FATAL: JWT_SECRET is weak ({reason}). "
                f'Generate a strong key: python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        logger.warning("jwt_secret_is_weak", reason=reason, hint="Replace before production deployment")


# ── 请求上下文 (Dependencies 注入) ──

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)


class AuthIdentity:
    """认证后的身份信息，注入到路由函数"""

    def __init__(self, method: str, subject: str = "", role: str = "user", tenant_id: str = "default"):
        self.method = method  # "api_key" | "jwt" | "none" (dev only)
        self.subject = subject
        self.role = role
        # AUTH-003: 多租户隔离 — 从 JWT payload 提取 tenant_id，默认 "default"
        self.tenant_id = tenant_id


async def require_auth(
    api_key: Annotated[str | None, Depends(api_key_header)] = None,
    bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    x_forwarded_for: Annotated[str | None, Header()] = None,
) -> AuthIdentity:
    """认证依赖 — 所有需要保护的路由用 Depends(require_auth)

    优先级: API Key > JWT Bearer > 开发模式放行(需显式开关)
    """
    settings = get_settings()

    # 1. API Key (AUTH-009: 支持多 key 轮换)
    all_keys = settings.auth.get_all_api_keys()
    if api_key and all_keys:
        if any(hmac.compare_digest(api_key, k) for k in all_keys):
            return AuthIdentity(method="api_key", subject="api_user")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API Key")

    # 2. JWT Bearer
    if bearer:
        try:
            payload = await verify_jwt(bearer.credentials)
            # AUTH-003: 从 JWT payload 读取 tenant_id claim
            return AuthIdentity(
                method="jwt",
                subject=payload.get("sub", ""),
                role=payload.get("role", "user"),
                tenant_id=payload.get("tenant_id", "default"),
            )
        except (AuthError, ValueError):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired JWT") from None

    # 3. 开发模式放行 — AUTH-002: 需显式开关 allow_dev_bypass=True (默认 False 拒绝)
    #   且仅非生产 + 未配置任何密钥时生效；授予 role=user (非 admin)
    #   AUTH-009: 同时检查 api_keys 列表，配置了任何 key 都不旁路
    if (
        settings.auth.allow_dev_bypass
        and not settings.is_production()
        and not all_keys
        and not settings.auth.jwt_secret
    ):
        # AUTH-002: 校验 X-Forwarded-For 识别代理后真实远端，记录日志便于审计
        real_remote = x_forwarded_for.split(",")[0].strip() if x_forwarded_for else "unknown"
        logger.warning("dev_mode_access_granted", subject="dev", role="user", real_remote=real_remote)
        return AuthIdentity(method="none", subject="dev", role="user")

    # 4. 未认证
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required (API Key or JWT)",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_admin(
    auth: Annotated[AuthIdentity, Depends(require_auth)],
) -> AuthIdentity:
    """管理员权限依赖 — 在 require_auth 基础上校验 role

    隐私API、审计日志等敏感端点用 Depends(require_admin) 保护。
    """
    if auth.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return auth


# ── JWT 工具 ──


def create_jwt(subject: str, role: str = "user", expire_minutes: int | None = None, tenant_id: str = "default") -> str:
    """签发 JWT

    Args:
        subject: 用户 ID
        role: 角色 (user/admin)
        expire_minutes: 过期分钟数
        tenant_id: 租户 ID (AUTH-003 多租户隔离，默认 "default")
    """
    settings = get_settings()
    if not settings.auth.jwt_secret:
        raise AuthError("JWT_SECRET not configured", code="JWT_NOT_CONFIGURED")

    # jwt_expire_minutes 正常为 int；当 settings 被 mock（测试）或配置异常时回退到 60 分钟
    try:
        default_minutes = int(settings.auth.jwt_expire_minutes)
    except (TypeError, ValueError):
        default_minutes = 60
    expire = datetime.now(UTC) + timedelta(minutes=expire_minutes or default_minutes)
    payload = {
        "sub": subject,
        "role": role,
        "tenant_id": tenant_id,  # AUTH-003: 多租户隔离 claim
        "iat": datetime.now(UTC),
        "exp": expire,
        "jti": secrets.token_urlsafe(32),  # 唯一 Token ID，用于黑名单
    }
    return jwt.encode(payload, settings.auth.jwt_secret, algorithm="HS256")


async def verify_jwt(token: str) -> dict[str, Any]:
    """验证 JWT，返回 payload 或抛出异常

    验证 JWT 签名完整性、payload 合法性以及黑名单状态。
    异步实现：直接 await Redis 黑名单检查，避免每请求创建线程。

    AUTH-010: strict_revocation_check=True 时强制要求 Redis 可用，
    Redis 未启用或不可用时 fail-closed (拒绝 token)。
    """
    settings = get_settings()
    if not settings.auth.jwt_secret:
        raise AuthError("JWT_SECRET not configured, cannot verify token", code="JWT_NOT_CONFIGURED")
    try:
        payload = jwt.decode(token, settings.auth.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise AuthError("JWT token has expired", code="JWT_EXPIRED") from None
    except jwt.InvalidTokenError:
        raise AuthError("Invalid JWT token", code="JWT_INVALID") from None

    # 检查黑名单 — 直接 await，无需 run_async 桥接
    jti = payload.get("jti")
    if jti:
        # AUTH-010: strict_revocation_check=True 时强制要求 Redis 可用，否则 fail-closed
        if not settings.redis.enabled:
            if settings.auth.strict_revocation_check:
                raise AuthError(
                    "Token revocation check unavailable (Redis disabled)",
                    code="JWT_BLACKLIST_UNAVAILABLE",
                ) from None
            # 非严格模式：Redis 未启用 = 不存在黑名单，token 不可能被撤销，直接放行
            return payload

        # Redis 已启用：检查黑名单
        try:
            from src.infra.cache.redis_cache import get_redis

            redis = await get_redis()
            if await redis.exists(f"{_TOKEN_BLACKLIST_PREFIX}{jti}"):
                raise AuthError("JWT token has been revoked", code="JWT_REVOKED")
        except AuthError:
            raise
        except Exception:
            logger.exception("jwt_blacklist_check_failed")
            if settings.auth.strict_revocation_check:
                raise AuthError(
                    "Token revocation check unavailable",
                    code="JWT_BLACKLIST_UNAVAILABLE",
                ) from None

    return payload


async def revoke_token(jti: str) -> None:
    """将 JWT jti 加入黑名单"""
    from src.infra.cache.redis_cache import get_redis

    try:
        redis = await get_redis()
        if redis is None:
            # Redis 未启用（开发模式），跳过黑名单写入
            logger.debug("token_revoke_skipped_redis_disabled", jti=jti[:8])
            return
        await redis.setex(f"{_TOKEN_BLACKLIST_PREFIX}{jti}", _TOKEN_BLACKLIST_TTL, "1")
        logger.info("token_revoked", jti=jti[:8])
    except Exception:
        logger.exception("token_revoke_failed", jti=jti[:8])
        raise AuthError("Failed to revoke token", code="TOKEN_REVOKE_FAILED") from None


# ── 路径白名单 (不需要认证) ──

PUBLIC_PATHS = frozenset(
    {
        "/health/live",
        "/health/ready",
        "/health/detail",
        "/docs",
        "/openapi.json",
        "/redoc",
        # 认证端点 — 注册/登录/刷新/忘记密码/重置密码不需要JWT
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        # AUTH-012: 忘记密码/重置密码端点公开访问（防枚举 + Token 自校验）
        "/api/v1/auth/forgot-password",
        "/api/v1/auth/reset-password",
        # 支付回调 — 微信/支付宝/Stripe 服务器回调，不带JWT
        "/api/v1/payment/wechat/callback",
        "/api/v1/payment/alipay/callback",
        "/api/v1/payment/stripe/callback",
        # 通道 Webhook — 飞书/企微/钉钉服务器回调
        "/api/v1/channel/feishu/webhook",
        "/api/v1/channel/wechat-work/webhook",
        "/api/v1/channel/dingtalk/webhook",
        # 电子签名回调 — 签名服务商回调不带JWT，靠签名验证
        "/api/v1/contract-webhook/callback",
        # 计费公开端点 — 套餐列表 + 收款码（用户浏览用，无需登录）
        "/api/v1/billing/plans",
        "/api/v1/billing/qrcode",
    }
)


def is_public_path(path: str) -> bool:
    """判断路径是否在白名单内"""
    return path in PUBLIC_PATHS


# ── ASGI 认证中间件 (后兜底) ──


class AuthMiddleware:
    """ASGI 认证中间件 — 全局保护，与 require_auth Depends 配合

    中间件验证 token 有效性（不仅仅是 header 存在），作为最后兜底。
    路由级 Depends(require_auth) 做更精细的注入，中间件防止遗漏。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        # AUTH-006: CORS 预检 (OPTIONS) 直接放行，交由内层 CORSMiddleware 处理
        # OPTIONS 请求不带认证 header，若被认证拦截会导致浏览器预检失败
        if scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        if is_public_path(path):
            await self.app(scope, receive, send)
            return

        settings = get_settings()

        # AUTH-009: 合并所有有效 API key (api_key + api_keys)
        all_keys = settings.auth.get_all_api_keys()

        # 开发模式放行 — AUTH-002: 需 allow_dev_bypass=True 显式开关 (默认 False 拒绝)
        # 仅限 localhost/127.0.0.1 或无client信息(如TestClient)
        # AUTH-009: 同时检查 api_keys 列表，配置了任何 key 都不旁路
        if (
            settings.auth.allow_dev_bypass
            and not settings.is_production()
            and not all_keys
            and not settings.auth.jwt_secret
        ):
            client = scope.get("client")
            client_ip = client[0] if client else "unknown"

            # 允许的本地地址列表
            allowed_local_ips = ("127.0.0.1", "::1", "localhost", "testclient", "0:0:0:0:0:0:0:1")

            if client is None or client_ip in allowed_local_ips:
                logger.warning("dev_mode_middleware_access", client_ip=client_ip, path=path, client=client)
                await self.app(scope, receive, send)
                return
            # 远程请求但无认证 → 拒绝并记录日志
            logger.warning("dev_mode_remote_access_denied", client_ip=client_ip, path=path)
            await self._send_401(send)
            return

        headers = dict(scope.get("headers", []))
        try:
            api_key = headers.get(b"x-api-key", b"").decode("utf-8", errors="strict")
            auth_header = headers.get(b"authorization", b"").decode("utf-8", errors="strict")
        except (UnicodeDecodeError, UnicodeError):
            logger.warning("auth_header_decode_failed", path=path)
            await self._send_401(send)
            return

        # 验证 API Key (AUTH-009: 支持多 key 轮换)
        if api_key and all_keys:
            if any(hmac.compare_digest(api_key, k) for k in all_keys):
                await self.app(scope, receive, send)
                return
            # API Key 提供了但不正确 → 立即拒绝
            await self._send_401(send)
            return

        # 验证 JWT Bearer
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                await verify_jwt(token)
                await self.app(scope, receive, send)
                return
            except (AuthError, ValueError):
                await self._send_401(send)
                return

        # 无认证 header
        await self._send_401(send)

    @staticmethod
    async def _send_401(send):
        body = b'{"detail":"Authentication required"}'
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    [b"content-type", b"application/json"],
                    [b"content-length", str(len(body)).encode()],
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
