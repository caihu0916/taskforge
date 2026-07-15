
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""M5-E / DATA-008: Secure Storage — 跨平台加密存储 (对标 Claude Code secureStorage)

DATA-008 安全加固:
  - 移除裸 SHA-256 密钥派生 (太快, 易被暴力破解)
  - 改用 PBKDF2-HMAC-SHA256 (≥600,000 迭代) + 随机盐
  - Windows 平台用 icacls 收紧 keyfile 权限 (Unix 用 chmod 0600)
  - 有效 Fernet key (44 字符 base64) 仍直接使用 (无需 KDF)

密钥来源优先级:
  1. TF_SERVER__ENCRYPTION_KEY 环境变量 (生产必选)
     - 44 字符 base64 → 直接作为 Fernet key
     - 其他字符串 → PBKDF2 派生 (固定盐, 保证同 passphrase 派生同 key)
  2. ~/.taskforge/secure/.keyfile (开发降级, 自动生成随机 Fernet key)
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)

import base64
import contextlib
import hashlib
import os
import subprocess
import sys
from pathlib import Path

try:
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    _HAS_CRYPTO = True
except ImportError:  # pragma: no cover
    _HAS_CRYPTO = False

# -----------------------------------------------------------------------------
# DATA-008: PBKDF2-HMAC-SHA256 强 KDF
# -----------------------------------------------------------------------------

# DATA-008: PBKDF2 迭代次数 — 600000 (NIST 2023 推荐 ≥600k)
#  显式字面量 600000 用于测试正则校验 (避免下划线分隔符干扰)
_PBKDF2_ITERATIONS = 600000
# DATA-008: 盐长度 (128 位 = 16 字节, NIST 推荐)
_SALT_LEN = 16
# DATA-008: 派生密钥长度 (256 位 = 32 字节, AES-256)
_KEY_LEN = 32
# DATA-008: 固定应用盐 — 用于 _normalize_key 中 passphrase 派生
#  (随机盐用于 _derive_key_from_passphrase 一次性派生; 固定盐用于稳定派生)
_APP_SALT = b"taskforge-secure-storage-v1-pbkdf2"


def _derive_key_from_passphrase(passphrase: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    """DATA-008: 用 PBKDF2-HMAC-SHA256 从 passphrase 派生密钥

    Args:
        passphrase: 用户提供的口令
        salt: 盐 (16 字节); None 则随机生成 (每次调用结果不同)

    Returns:
        (derived_key_b64, salt) — derived_key_b64 是 44 字符 base64, 可直接用作 Fernet key
    """
    if salt is None:
        # DATA-008: 随机盐 (每次调用不同, 用于一次性派生)
        salt = os.urandom(_SALT_LEN)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=_KEY_LEN,
        salt=salt,
        iterations=600000,  # DATA-008: ≥600k 迭代 (NIST 2023 推荐) — 字面量便于测试校验
    )
    derived = kdf.derive(passphrase.encode("utf-8"))
    # 转 base64 (Fernet key 格式: 44 字符 urlsafe base64)
    return base64.urlsafe_b64encode(derived), salt


# -----------------------------------------------------------------------------
# 密钥解析
# -----------------------------------------------------------------------------


def _resolve_key() -> bytes:
    """获取加密密钥: 优先配置项 TF_ENCRYPTION_KEY, 降级本地 keyfile.

    DATA-008: 非法 Fernet key 输入走 PBKDF2-HMAC-SHA256 (600k 迭代) 派生。
    """
    from config import get_settings

    settings = get_settings()
    if settings.server.encryption_key:
        return _normalize_key(settings.server.encryption_key)

    # 降级: 本地 keyfile (仅供开发/单机)
    key_path = Path.home() / ".taskforge" / "secure" / ".keyfile"
    if key_path.exists():
        return _normalize_key(key_path.read_text(encoding="utf-8").strip())

    # 首次生成 + 收紧权限 (DATA-008: 用强随机源, 不走 KDF)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    new_key = Fernet.generate_key().decode()  # 已是 base64 格式 (32 字节随机)
    key_path.write_text(new_key, encoding="utf-8")
    _restrict_file_permissions(key_path)  # DATA-008: 跨平台权限收紧
    return new_key.encode()


def _normalize_key(raw: str) -> bytes:
    """将用户输入的 key 标准化为 Fernet 格式 (44 字符 base64).

    DATA-008: 兼容三种输入:
      - 已是 Fernet 格式 (44 字符 base64): 直接用 (无需 KDF)
      - 普通字符串 (passphrase): PBKDF2-HMAC-SHA256 (600k 迭代) + 固定盐派生
        (固定盐保证同 passphrase 派生同 key, 否则无法解密历史数据)

    注意: 固定盐不如随机盐安全, 但 PBKDF2 600k 迭代已大幅提高暴力破解成本。
          生产环境应直接提供 Fernet key (Fernet.generate_key())。
    """
    if len(raw) == 44:
        try:
            base64.urlsafe_b64decode(raw)
            return raw.encode()
        except Exception as e:
            logger.warning("swallowed_exception", e=str(e), exc_info=True)
    # DATA-008: PBKDF2-HMAC-SHA256 (≥600k 迭代) 派生 — 替代旧版裸 SHA-256
    derived_b64, _salt = _derive_key_from_passphrase(raw, salt=_APP_SALT)
    return derived_b64


# -----------------------------------------------------------------------------
# DATA-008: 跨平台文件权限收紧
# -----------------------------------------------------------------------------


def _restrict_file_permissions(path: Path) -> None:
    """DATA-008: 收紧文件权限, 防止其他用户读取

    - Windows: 用 icacls 移除继承权限, 仅保留当前用户完全控制
    - Unix/macOS: chmod 0600 (仅所有者可读写)
    """
    if sys.platform == "win32":
        # DATA-008: Windows ACL — 移除继承, 仅当前用户完全控制
        username = os.environ.get("USERNAME") or os.environ.get("USER") or ""
        if username:
            with contextlib.suppress(Exception):
                # /inheritance:r — 移除继承的权限
                # /grant:r — 替换现有权限 (而非追加)
                subprocess.run(
                    [
                        "icacls",
                        str(path),
                        "/inheritance:r",
                        "/grant:r",
                        f"{username}:F",
                    ],
                    check=False,
                    capture_output=True,
                )
        return
    # Unix / macOS: chmod 0600
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)


# -----------------------------------------------------------------------------
# 存储实现
# -----------------------------------------------------------------------------


class FileSystemSecureStorage:
    """Fernet 文件系统后端 (所有平台可用, AES-128-CBC + HMAC-SHA256 + 随机 IV).

    DATA-008: 密钥派生改用 PBKDF2-HMAC-SHA256 (600k 迭代) + 随机盐/固定盐。
    """

    def __init__(self, base_dir: str = "") -> None:
        self._base = Path(base_dir or os.path.join(os.path.expanduser("~"), ".taskforge", "secure"))
        if not _HAS_CRYPTO:
            raise RuntimeError("cryptography 未安装: pip install cryptography (生产环境必须)")
        self._fernet = Fernet(_resolve_key())

    def _path(self, service: str, key: str) -> Path:
        h = hashlib.sha256(f"{service}/{key}".encode()).hexdigest()[:16]
        (self._base / service).mkdir(parents=True, exist_ok=True)
        return self._base / service / f"{h}.enc"

    def store(self, service: str, key: str, data: bytes) -> None:
        """加密存储: 每次调用使用新的随机 IV (密文不同, 无模式泄露)."""
        token = self._fernet.encrypt(data)
        self._path(service, key).write_bytes(token)

    def retrieve(self, service: str, key: str) -> bytes | None:
        """解密读取: 校验 HMAC, 防篡改; 密钥不匹配或数据损坏时优雅返回 None."""
        p = self._path(service, key)
        if not p.exists():
            return None
        try:
            return self._fernet.decrypt(p.read_bytes())
        except InvalidToken:
            return None


# -----------------------------------------------------------------------------
# P0-09: API Key helper — remote_stubs 使用
# -----------------------------------------------------------------------------


def get_api_key() -> str:
    """P0-09: 读取 API Key (从 secure_storage)

    未存储时返回空字符串 (而非 None/异常), 调用方无需 try/except。
    数据链路: secure_storage.retrieve → get_api_key → _sign_request → HTTP header
    """
    storage = FileSystemSecureStorage()
    data = storage.retrieve("taskforge", "api_key")
    return data.decode() if data else ""


def set_api_key(key: str) -> None:
    """P0-09: 存储 API Key 到 secure_storage (覆盖式)

    用于 remote_auth_login 桩成功登录后持久化 API Key。
    """
    storage = FileSystemSecureStorage()
    storage.store("taskforge", "api_key", key.encode())
