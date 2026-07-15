
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""配置共享常量 — PROJECT_ROOT + 弱密钥黑名单(SHA256 指纹)"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _is_weak_encryption_key(key: str) -> bool:
    import hashlib

    return f"sha256:{hashlib.sha256(key.encode()).hexdigest()}" in _WEAK_KEY_FINGERPRINTS


_WEAK_KEY_FINGERPRINTS = frozenset(
    {
        "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "sha256:a268e47c2aabfd8c9e6eac615564d426d33f08bcd7fd2789315517676987a97f",
        "sha256:42e66397f5a6ca41092046a5ebe7fa32788c9b387cdd2e60a53e60058de03ae5",
        "sha256:97f0a723b456df0d82c8f77fb2f10edfead50211de28f18af961c484638aa062",
    }
)
