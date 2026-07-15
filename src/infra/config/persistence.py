
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

""".env 持久化工具 — 将运行时配置变更原子写入 .env 文件

从 src/api/routes/settings.py 提取，移至基础设施层以避免 engine → API 循环依赖。
"""

from __future__ import annotations

from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILE = PROJECT_ROOT / ".env"


def persist_env(updates: dict[str, str]) -> None:
    """将运行时配置变更持久化到 .env 文件（追加或更新已有 key）

    SEC-10: 敏感字段写入前标记提醒，使用原子写入防并发丢失
    """
    existing: dict[str, str] = {}
    if _ENV_FILE.exists():
        for raw_line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()

    existing.update(updates)

    # SEC-10: 敏感字段加密后写入（如果加密可用）
    _sensitive_key_suffixes = ("API_KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWORD_HASH")
    lines = []
    for k, v in existing.items():
        is_sensitive = any(s in k.upper() for s in _sensitive_key_suffixes)
        value = v
        if is_sensitive and value and not value.startswith("enc:"):
            try:
                from src.infra.crypto.encryption import encrypt_value, is_encryption_available

                if is_encryption_available():
                    value = f"enc:{encrypt_value(value)}"
                    logger.info("settings_sensitive_encrypted", key=k)
            except Exception:
                logger.warning("settings_encrypt_failed_writing_plain", key=k, exc_info=True)
        lines.append(f"{k}={value}")

    # SEC-10: 原子写入 — 先写临时文件再 rename，防并发丢失
    tmp_path = _ENV_FILE.with_suffix(".env.tmp")
    try:
        tmp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tmp_path.replace(_ENV_FILE)
    except Exception as e:
        logger.error("settings_persist_failed", error=str(e), exc_info=True)
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception as e:
            logger.warning("exception_swallowed", context="tmp_path.unlink(missing_ok=True)", exc_info=True)
        raise
    logger.info("settings_persisted_to_env", keys=list(updates.keys()))
