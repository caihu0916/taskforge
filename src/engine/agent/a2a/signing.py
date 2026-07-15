
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""A2A 消息签名/验签模块 (AGENT-015)

职责:
  - 对 A2A 消息(payload)做 HMAC-SHA256 签名
  - 验证收到的消息签名是否匹配 — 防篡改/防伪造

设计说明:
  - 当前项目尚未引入完整 A2A 消息传递通道, 此模块作为未来引入时的签名基础设施
  - 后续若引入 mTLS, 可在此模块扩展证书校验逻辑
  - 签名算法: HMAC-SHA256, 输出 hex 字符串 (64 字符)
  - secret 来源: 共享密钥 (环境变量 TF_A2A__SIGNING_SECRET) 或 mTLS 通道派生密钥

用法:
    from src.engine.agent.a2a.signing import sign_message, verify_message

    payload = b'{"task_id":"t-001","action":"run"}'
    sig = sign_message(payload, secret="shared-secret")
    #接收方:
    if not verify_message(payload, sig, secret="shared-secret"):
        raise ValueError("A2A 消息签名验证失败")

未来扩展:
  - 引入 mTLS 时, 添加 verify_mtls_certificate() 函数
  - 引入非对称签名时, 添加 sign_with_private_key() / verify_with_public_key()
  - 引入消息序列号防重放时, 在 payload 中嵌入 nonce + timestamp
"""

from __future__ import annotations

import hmac
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# 签名算法 — HMAC-SHA256, 输出 hex
_HASH_NAME = "sha256"
_HEX_DIGEST_LENGTH = 64


def _normalize_payload(payload: Any) -> bytes:
    """将 payload 标准化为 bytes — 用于稳定签名

    支持:
      - bytes: 原样返回
      - str: utf-8 编码
      - dict/list: JSON 序列化 (sort_keys 保证字段顺序稳定)
    """
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8")
    import json

    return json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")


def _normalize_secret(secret: str) -> bytes:
    """将 secret 标准化为 bytes"""
    if isinstance(secret, bytes):
        return secret
    return secret.encode("utf-8")


def sign_message(payload: Any, *, secret: str) -> str:
    """对 A2A 消息生成 HMAC-SHA256 签名

    Args:
        payload: 消息内容 (bytes/str/dict/list)
        secret: 共享密钥

    Returns:
        hex 签名字符串 (64 字符)
    """
    payload_bytes = _normalize_payload(payload)
    secret_bytes = _normalize_secret(secret)
    return hmac.new(secret_bytes, payload_bytes, _HASH_NAME).hexdigest()


def verify_message(payload: Any, signature: str, *, secret: str) -> bool:
    """验证 A2A 消息签名 — 使用恒定时间比较防时序攻击

    Args:
        payload: 消息内容 (bytes/str/dict/list)
        signature: 待验证的 hex 签名字符串
        secret: 共享密钥

    Returns:
        True = 签名匹配 (消息可信)
        False = 签名不匹配或格式非法 (消息被篡改/伪造)
    """
    if not signature or not isinstance(signature, str):
        return False
    try:
        expected = sign_message(payload, secret=secret)
    except Exception as e:
        logger.debug("a2a_sign_compute_failed", error=str(e))
        return False
    # 恒定时间比较 — 防时序攻击
    return hmac.compare_digest(expected, signature)


def get_signing_secret() -> str:
    """获取 A2A 签名密钥 (通过 Settings 统一管理)

    Returns:
        签名密钥字符串

    Raises:
        RuntimeError: 未配置 TF_BRIDGE__A2A_SIGNING_SECRET
    """
    from config import get_settings

    secret = get_settings().bridge.a2a_signing_secret
    if not secret:
        raise RuntimeError("A2A 签名密钥未配置 — 请设置 TF_BRIDGE__A2A_SIGNING_SECRET 环境变量")
    return secret
