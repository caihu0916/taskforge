
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""P0-17: LLMRouter 双模式桩版本测试 (TDD RED 阶段)

覆盖:
  - _detect_mode() 三种模式检测 (local/remote/unavailable)
  - chat() local/remote/unavailable 分发
  - stream_chat() local/remote/unavailable 分发
  - 参数保持 (profile/provider/model/user_id 透传)

数据链路: LLMRouter → _detect_mode → OllamaProvider(local) / remote_stubs(remote)
"""

from __future__ import annotations

import pytest

_TEST_FERNET_KEY = "JHEc0WrVs7NDC7qg8EkQsfZN0UYEqm1twRQHsR5PW9E="


@pytest.fixture
def isolated_settings(monkeypatch, tmp_path):
    """隔离 Settings 单例 + secure_storage"""
    from src.infra.config.settings import reset_settings

    reset_settings()
    monkeypatch.setenv("TF_SERVER__ENCRYPTION_KEY", _TEST_FERNET_KEY)
    import os

    monkeypatch.setattr(os.path, "expanduser", lambda _: str(tmp_path))
    yield
    reset_settings()


# ---------- _detect_mode() ----------


def test_detect_mode_local_when_ollama_available_no_api_key(isolated_settings, monkeypatch):
    """无 API Key + 有 Ollama → local 模式 — 免费本地优先"""
    import asyncio

    # 无 API Key (默认)
    # Mock OllamaProvider.is_available → True
    from src.engine.llm._local_provider import OllamaProvider

    async def mock_is_available(self):
        return True

    monkeypatch.setattr(OllamaProvider, "is_available", mock_is_available)

    from src.engine.llm._router_core import LLMRouter

    router = LLMRouter()
    mode = asyncio.run(router._detect_mode())
    assert mode == "local"


def test_detect_mode_remote_when_api_key_no_ollama(isolated_settings, monkeypatch):
    """有 API Key + 无 Ollama → remote 模式 — SaaS 远程调用"""
    import asyncio

    from src.infra.secure_storage import set_api_key

    set_api_key("sk-test-123")

    from src.engine.llm._local_provider import OllamaProvider

    async def mock_is_available(self):
        return False

    monkeypatch.setattr(OllamaProvider, "is_available", mock_is_available)

    from src.engine.llm._router_core import LLMRouter

    router = LLMRouter()
    mode = asyncio.run(router._detect_mode())
    assert mode == "remote"


def test_detect_mode_local_takes_precedence_over_remote(isolated_settings, monkeypatch):
    """有 API Key + 有 Ollama → local 模式 — 免费优先于付费"""
    import asyncio

    from src.infra.secure_storage import set_api_key

    set_api_key("sk-test-123")

    from src.engine.llm._local_provider import OllamaProvider

    async def mock_is_available(self):
        return True

    monkeypatch.setattr(OllamaProvider, "is_available", mock_is_available)

    from src.engine.llm._router_core import LLMRouter

    router = LLMRouter()
    mode = asyncio.run(router._detect_mode())
    assert mode == "local"


def test_detect_mode_unavailable_when_no_api_key_no_ollama(isolated_settings, monkeypatch):
    """无 API Key + 无 Ollama → unavailable 模式 — 引导用户配置"""
    import asyncio

    from src.engine.llm._local_provider import OllamaProvider

    async def mock_is_available(self):
        return False

    monkeypatch.setattr(OllamaProvider, "is_available", mock_is_available)

    from src.engine.llm._router_core import LLMRouter

    router = LLMRouter()
    mode = asyncio.run(router._detect_mode())
    assert mode == "unavailable"


# ---------- chat() ----------


def test_chat_local_mode_calls_ollama(isolated_settings, monkeypatch):
    """local 模式 chat 调用 OllamaProvider.chat — 本地 LLM 对话"""
    import asyncio

    from src.engine.llm._router_core import LLMRouter

    router = LLMRouter()

    # Mock _detect_mode → "local"
    async def mock_detect(self):
        return "local"

    monkeypatch.setattr(LLMRouter, "_detect_mode", mock_detect)

    # Mock OllamaProvider.chat
    from src.engine.llm._local_provider import OllamaProvider

    async def mock_chat(self, messages, **kwargs):
        return {"content": "local response", "provider": "ollama"}

    monkeypatch.setattr(OllamaProvider, "chat", mock_chat)

    result = asyncio.run(router.chat([{"role": "user", "content": "hi"}], model="qwen2.5:7b"))
    assert result["content"] == "local response"
    assert result["provider"] == "ollama"


def test_chat_remote_mode_calls_remote_stubs(isolated_settings, monkeypatch):
    """remote 模式 chat 调用 remote_llm_chat — SaaS 远程对话"""
    import asyncio

    from src.engine.llm._router_core import LLMRouter

    router = LLMRouter()

    async def mock_detect(self):
        return "remote"

    monkeypatch.setattr(LLMRouter, "_detect_mode", mock_detect)

    # Mock remote_llm_chat
    async def mock_remote_chat(messages, **kwargs):
        return {"content": "remote response", "provider": "remote"}

    from src.infra import remote_stubs

    monkeypatch.setattr(remote_stubs, "remote_llm_chat", mock_remote_chat)

    result = asyncio.run(router.chat([{"role": "user", "content": "hi"}], model="gpt-4"))
    assert result["content"] == "remote response"


def test_chat_unavailable_raises_with_guide(isolated_settings, monkeypatch):
    """unavailable 模式 chat 抛 RuntimeError 含注册引导 — 用户知道下一步"""
    import asyncio

    from src.engine.llm._router_core import LLMRouter

    router = LLMRouter()

    async def mock_detect(self):
        return "unavailable"

    monkeypatch.setattr(LLMRouter, "_detect_mode", mock_detect)

    with pytest.raises(RuntimeError, match=r"Ollama|API Key|注册|配置"):
        asyncio.run(router.chat([{"role": "user", "content": "hi"}]))


def test_chat_preserves_all_parameters(isolated_settings, monkeypatch):
    """chat 透传 profile/provider/model/user_id — 上层调用零感知"""
    import asyncio

    from src.engine.llm._router_core import LLMRouter

    router = LLMRouter()

    async def mock_detect(self):
        return "local"

    monkeypatch.setattr(LLMRouter, "_detect_mode", mock_detect)

    # 捕获 OllamaProvider.chat 收到的参数
    captured = {}

    from src.engine.llm._local_provider import OllamaProvider

    async def mock_chat(self, messages, *, model="", temperature=0.7, max_tokens=4096, **kwargs):
        captured["messages"] = messages
        captured["model"] = model
        captured["temperature"] = temperature
        captured["max_tokens"] = max_tokens
        return {"content": "ok"}

    monkeypatch.setattr(OllamaProvider, "chat", mock_chat)

    asyncio.run(
        router.chat(
            [{"role": "user", "content": "hello"}],
            profile="deep",
            provider="ollama",
            model="qwen2.5:7b",
            temperature=0.3,
            max_tokens=512,
            user_id="user-123",
        )
    )

    assert captured["messages"] == [{"role": "user", "content": "hello"}]
    assert captured["model"] == "qwen2.5:7b"
    assert captured["temperature"] == 0.3
    assert captured["max_tokens"] == 512


# ---------- stream_chat() ----------


def test_stream_chat_local_mode_yields_from_ollama(isolated_settings, monkeypatch):
    """local 模式 stream_chat yield OllamaProvider 内容 — 本地流式对话"""
    import asyncio

    from src.engine.llm._router_core import LLMRouter

    router = LLMRouter()

    async def mock_detect(self):
        return "local"

    monkeypatch.setattr(LLMRouter, "_detect_mode", mock_detect)

    from src.engine.llm._local_provider import OllamaProvider

    async def mock_stream(self, messages, **kwargs):
        for chunk in ["Hello", " world", "!"]:
            yield chunk

    monkeypatch.setattr(OllamaProvider, "stream_chat", mock_stream)

    async def collect():
        chunks = []
        async for chunk in router.stream_chat([{"role": "user", "content": "hi"}]):
            chunks.append(chunk)
        return chunks

    result = asyncio.run(collect())
    assert result == ["Hello", " world", "!"]


def test_stream_chat_remote_mode_yields_from_remote(isolated_settings, monkeypatch):
    """remote 模式 stream_chat yield remote_llm_stream — SaaS 流式对话"""
    import asyncio

    from src.engine.llm._router_core import LLMRouter

    router = LLMRouter()

    async def mock_detect(self):
        return "remote"

    monkeypatch.setattr(LLMRouter, "_detect_mode", mock_detect)

    async def mock_remote_stream(messages, **kwargs):
        for chunk in ["remote", " chunk"]:
            yield chunk

    from src.infra import remote_stubs

    monkeypatch.setattr(remote_stubs, "remote_llm_stream", mock_remote_stream)

    async def collect():
        chunks = []
        async for chunk in router.stream_chat([{"role": "user", "content": "hi"}]):
            chunks.append(chunk)
        return chunks

    result = asyncio.run(collect())
    assert result == ["remote", " chunk"]


def test_stream_chat_unavailable_raises(isolated_settings, monkeypatch):
    """unavailable 模式 stream_chat 抛 RuntimeError — 与 chat 一致"""
    import asyncio

    from src.engine.llm._router_core import LLMRouter

    router = LLMRouter()

    async def mock_detect(self):
        return "unavailable"

    monkeypatch.setattr(LLMRouter, "_detect_mode", mock_detect)

    async def consume():
        async for _ in router.stream_chat([{"role": "user", "content": "hi"}]):
            pass

    with pytest.raises(RuntimeError, match=r"Ollama|API Key|注册|配置"):
        asyncio.run(consume())


# ---------- 类名与接口契约 ----------


def test_llm_router_class_name(isolated_settings):
    """类名为 LLMRouter — 与主项目一致, 上层调用零感知"""
    from src.engine.llm._router_core import LLMRouter

    router = LLMRouter()
    assert router.__class__.__name__ == "LLMRouter"
