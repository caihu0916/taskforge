
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""TaskForge 登录安全模块 — 限流 + 暴力破解防护

功能:
  - 登录限流: 5次/分钟
  - 暴力破解防护: 5次失败锁定15分钟
  - IP限流: 20次/分钟

AUTH-008:
  - 支持 Redis 后端 (rate_limit_backend="redis")，实现分布式限流
  - 多实例部署时，登录失败/锁定状态跨实例共享
  - 内存后端保留作为单实例/测试降级
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

import structlog

logger = structlog.get_logger(__name__)

# ── Redis key 前缀 (分布式限流) ──
_REDIS_USER_LOCK_PREFIX = "auth:login:lock:"  # 存在即锁定，TTL=lockout 秒
_REDIS_USER_FAIL_PREFIX = "auth:login:fail:"  # 失败计数，TTL=60s 窗口
_REDIS_IP_PREFIX = "auth:login:ip:"  # IP 计数，TTL=60s 窗口


@dataclass
class LoginAttempt:
    """登录尝试记录"""

    count: int = 0
    first_failure: float = 0.0
    last_failure: float = 0.0
    locked_until: float = 0.0


class LoginSecurityManager:
    """登录安全管理器

    策略:
      - 单用户: 5次失败/分钟，锁定15分钟
      - 单IP: 20次尝试/分钟

    AUTH-008: 支持 rate_limit_backend 参数
      - "memory" (默认): 单实例内存，向后兼容
      - "redis": 分布式限流，跨实例共享锁定状态
    """

    # 配置
    MAX_FAILURES_PER_USER = 5
    USER_LOCKOUT_MINUTES = 15
    MAX_ATTEMPTS_PER_IP = 20
    IP_RATE_LIMIT_MINUTES = 1

    def __init__(self, rate_limit_backend: Literal["memory", "redis"] = "memory"):
        # AUTH-008: 记录限流后端模式
        self._rate_limit_backend: Literal["memory", "redis"] = rate_limit_backend
        self._user_attempts: dict[str, LoginAttempt] = {}
        self._ip_attempts: dict[str, list[float]] = {}

    def check_user_lockout(self, identifier: str) -> tuple[bool, str]:
        """检查用户是否被锁定 (内存后端，向后兼容)

        Args:
            identifier: 用户标识（email或user_id）

        Returns:
            (is_locked, message)
        """
        now = time.time()
        attempt = self._user_attempts.get(identifier)

        if attempt is None:
            return False, ""

        # 检查是否在锁定期内
        if attempt.locked_until > now:
            remaining = int(attempt.locked_until - now)
            return True, f"账号已被锁定，请{remaining}秒后重试"

        # 检查是否超过失败次数
        if attempt.count >= self.MAX_FAILURES_PER_USER:
            # 检查是否在1分钟窗口内
            if now - attempt.first_failure < 60:
                # 锁定15分钟
                attempt.locked_until = now + self.USER_LOCKOUT_MINUTES * 60
                logger.warning(
                    "user_locked_out",
                    identifier=identifier,
                    failures=attempt.count,
                    lockout_seconds=self.USER_LOCKOUT_MINUTES * 60,
                )
                return True, f"登录失败次数过多，请{self.USER_LOCKOUT_MINUTES}分钟后重试"
            # 窗口已过，重置计数
            attempt.count = 0
            attempt.first_failure = now

        return False, ""

    async def check_user_lockout_async(self, identifier: str) -> tuple[bool, str]:
        """检查用户是否被锁定 (异步，支持 Redis 后端)

        AUTH-008: redis 后端走分布式路径，内存后端复用同步逻辑
        """
        if self._rate_limit_backend != "redis":
            return self.check_user_lockout(identifier)

        # ── Redis 后端：检查锁定 key 是否存在 ──
        try:
            from src.infra.cache.redis_cache import get_redis

            redis = await get_redis()
            if redis is None:
                # Redis 未启用 → 降级到内存（配置不一致时的防御）
                return self.check_user_lockout(identifier)
            lock_key = f"{_REDIS_USER_LOCK_PREFIX}{identifier}"
            # get 返回非 None 即锁定 (key 带 TTL 自动过期)
            val = await redis.get(lock_key)
            if val is not None:
                return True, "账号已被锁定，请稍后重试"
        except Exception:
            logger.exception("redis_user_lockout_check_failed", identifier=identifier)
            # Redis 故障时降级到内存 (避免 Redis 不可用时锁死登录)
            return self.check_user_lockout(identifier)

        return False, ""

    async def record_user_failure_async(self, identifier: str) -> None:
        """记录用户登录失败 (异步，支持 Redis 后端)

        AUTH-008: redis 后端用 INCR + TTL 实现分布式失败计数
        达到阈值时设置锁定 key
        """
        if self._rate_limit_backend != "redis":
            self.record_user_failure(identifier)
            return

        try:
            from src.infra.cache.redis_cache import get_redis

            redis = await get_redis()
            if redis is None:
                # Redis 未启用 → 降级到内存（配置不一致时的防御）
                self.record_user_failure(identifier)
                return
            fail_key = f"{_REDIS_USER_FAIL_PREFIX}{identifier}"
            # INCR 失败计数，首次设置 60s 窗口 TTL
            count = await redis.incr(fail_key)
            if count == 1:
                await redis.expire(fail_key, 60)

            # 达到阈值 → 设置锁定 key
            if count >= self.MAX_FAILURES_PER_USER:
                lock_key = f"{_REDIS_USER_LOCK_PREFIX}{identifier}"
                await redis.setex(
                    lock_key,
                    self.USER_LOCKOUT_MINUTES * 60,
                    str(count),
                )
                logger.warning(
                    "user_locked_out_redis",
                    identifier=identifier,
                    failures=count,
                    lockout_seconds=self.USER_LOCKOUT_MINUTES * 60,
                )
            logger.info("login_failure_recorded_redis", identifier=identifier, failures=count)
        except Exception:
            logger.exception("redis_user_failure_record_failed", identifier=identifier)
            # 降级到内存
            self.record_user_failure(identifier)

    async def reset_user_failures_async(self, identifier: str) -> None:
        """登录成功后重置失败计数 (异步，支持 Redis 后端)"""
        if self._rate_limit_backend != "redis":
            self.reset_user_failures(identifier)
            return

        try:
            from src.infra.cache.redis_cache import get_redis

            redis = await get_redis()
            if redis is None:
                # Redis 未启用 → 降级到内存（配置不一致时的防御）
                self.reset_user_failures(identifier)
                return
            await redis.delete(f"{_REDIS_USER_FAIL_PREFIX}{identifier}")
            await redis.delete(f"{_REDIS_USER_LOCK_PREFIX}{identifier}")
            logger.info("login_failures_reset_redis", identifier=identifier)
        except Exception:
            logger.exception("redis_user_reset_failed", identifier=identifier)
            self.reset_user_failures(identifier)

    def record_user_failure(self, identifier: str) -> None:
        """记录用户登录失败"""
        now = time.time()
        attempt = self._user_attempts.get(identifier)

        if attempt is None:
            attempt = LoginAttempt()
            self._user_attempts[identifier] = attempt

        attempt.count += 1
        attempt.last_failure = now

        if attempt.count == 1:
            attempt.first_failure = now

        logger.info(
            "login_failure_recorded",
            identifier=identifier,
            failures=attempt.count,
        )

    def reset_user_failures(self, identifier: str) -> None:
        """登录成功后重置失败计数"""
        if identifier in self._user_attempts:
            del self._user_attempts[identifier]
            logger.info("login_failures_reset", identifier=identifier)

    def check_ip_rate_limit(self, client_ip: str) -> tuple[bool, str]:
        """检查IP速率限制

        Args:
            client_ip: 客户端IP

        Returns:
            (is_limited, message)
        """
        now = time.time()
        window_start = now - self.IP_RATE_LIMIT_MINUTES * 60

        attempts = self._ip_attempts.get(client_ip, [])

        # 清理过期记录
        attempts = [t for t in attempts if t > window_start]
        self._ip_attempts[client_ip] = attempts

        if len(attempts) >= self.MAX_ATTEMPTS_PER_IP:
            logger.warning(
                "ip_rate_limit_exceeded",
                client_ip=client_ip,
                attempts=len(attempts),
            )
            return True, "请求过于频繁，请稍后再试"

        # 记录本次尝试
        attempts.append(now)

        return False, ""

    def get_user_status(self, identifier: str) -> dict:
        """获取用户登录状态（供管理员查看）"""
        attempt = self._user_attempts.get(identifier)
        if attempt is None:
            return {"status": "normal", "failures": 0}

        now = time.time()
        if attempt.locked_until > now:
            remaining = int(attempt.locked_until - now)
            return {
                "status": "locked",
                "failures": attempt.count,
                "lockout_remaining_seconds": remaining,
            }

        return {
            "status": "normal",
            "failures": attempt.count,
            "window_remaining_seconds": max(0, int(60 - (now - attempt.first_failure))),
        }

    def cleanup_expired(self) -> None:
        """清理过期记录（定期调用）"""
        now = time.time()
        window_start = now - 60

        # 清理用户尝试记录
        expired_users = [
            uid
            for uid, attempt in self._user_attempts.items()
            if attempt.locked_until < now and now - attempt.first_failure > 60
        ]
        for uid in expired_users:
            del self._user_attempts[uid]

        # 清理IP尝试记录
        expired_ips = [ip for ip, attempts in self._ip_attempts.items() if not attempts or max(attempts) < window_start]
        for ip in expired_ips:
            del self._ip_attempts[ip]


# ── 全局实例 ──

_login_security: LoginSecurityManager | None = None


def get_login_security() -> LoginSecurityManager:
    """获取登录安全管理器单例

    AUTH-008: 根据配置 rate_limit_backend 选择后端
    """
    global _login_security
    if _login_security is None:
        # 读取配置选择后端
        try:
            from config import get_settings

            backend = get_settings().auth.rate_limit_backend
        except Exception as exc:
            logger.debug("exception_handled", error=str(exc))
            backend = "memory"
        _login_security = LoginSecurityManager(rate_limit_backend=backend)
    return _login_security


def reset_login_security() -> None:
    """重置单例 (测试用)"""
    global _login_security
    _login_security = None
