
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""P0-16: OllamaProvider 本地 LLM Provider 测试 (TDD RED 阶段)

覆盖:
  - name 属性
  - 构造函数 base_url 默认值/自定义
  - is_available() True/False
  - chat() 返回格式/POST路由/参数传递/HTTP错误
  - stream_chat() yield内容/跳过空行
  - list_models() 返回模型列表/连接错误返回空
  - count_tokens() 中英文估算

数据链路: OllamaProvider → httpx.AsyncClient → localhost:11434 → Ollama API
"""

from __future__ import annotations

import json

import pytest

# 复用 remote_stubs 测试的 httpx mock 模式
_TEST_FERNET_KEY = "JHEc0WrVs7NDC7qg8EkQsfZN0UYEqm1twRQHsR5PW9E="


@pytest.fixture
def isolated_settings(monkeypatch, tmp_path):
    """隔离 Settings 单例, 确保 TF_LLM__* 环境变量被重新读取"""
    from src.infra.config.settings import reset_settings

    reset_settings()
    monkeypatch.setenv("TF_SERVER__ENCRYPTION_KEY", _TEST_FERNET_KEY)
    yield
    reset_settings()


def _patch_httpx_with_mock(monkeypatch, handler):
    """用 httpx.MockTransport 替换 httpx.AsyncClient, 注入 handler 处理请求"""
    import httpx

    mock_transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def patched_client(*args, **kwargs):
        kwargs["transport"] = mock_transport
        return original_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched_client)
    return mock_transport


# ---------- name 属性 ----------


def test_ollama_provider_name_returns_ollama(isolated_settings):
    """name 属性返回 'ollama' — Provider 身份标识"""
    from src.engine.llm._local_provider import OllamaProvider

    provider = OllamaProvider()
    assert provider.name == "ollama"


# ---------- 构造函数 ----------


def test_ollama_provider_default_base_url(isolated_settings):
    """未配置时 base_url 默认 http://localhost:11434 — Ollama 标准端口"""
    from src.engine.llm._local_provider import OllamaProvider

    provider = OllamaProvider()
    assert provider._base_url == "http://localhost:11434"


def test_ollama_provider_custom_base_url(isolated_settings):
    """显式传入 base_url 时覆盖默认值 — 远程 Ollama 服务器场景"""
    from src.engine.llm._local_provider import OllamaProvider

    provider = OllamaProvider(base_url="http://192.168.1.100:11434")
    assert provider._base_url == "http://192.168.1.100:11434"


def test_ollama_provider_base_url_from_env(isolated_settings, monkeypatch):
    """base_url 从 TF_LLM__BASE_URL 读取 — 部署环境可配置"""
    monkeypatch.setenv("TF_LLM__BASE_URL", "http://ollama-host:11434")
    from src.infra.config.settings import reset_settings

    reset_settings()
    from src.engine.llm._local_provider import OllamaProvider

    provider = OllamaProvider()
    assert provider._base_url == "http://ollama-host:11434"


# ---------- is_available() ----------


def test_is_available_returns_true_when_ollama_responds(isolated_settings, monkeypatch):
    """Ollama 响应 /api/tags 200 时 is_available 返回 True — 本地 LLM 可用"""
    import asyncio

    import httpx

    def handler(request):
        return httpx.Response(200, json={"models": []})

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.engine.llm._local_provider import OllamaProvider

    provider = OllamaProvider()
    assert asyncio.run(provider.is_available()) is True


def test_is_available_returns_false_on_connection_error(isolated_settings, monkeypatch):
    """Ollama 未启动时 is_available 返回 False (不抛异常) — graceful 降级"""
    import asyncio

    import httpx

    def handler(request):
        raise httpx.ConnectError("Connection refused")

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.engine.llm._local_provider import OllamaProvider

    provider = OllamaProvider()
    assert asyncio.run(provider.is_available()) is False


# ---------- chat() ----------


def test_chat_returns_correct_format(isolated_settings, monkeypatch):
    """chat 返回 {content, model, provider, usage} — 与 LLMProvider 协议对齐"""
    import asyncio

    import httpx

    def handler(request):
        return httpx.Response(
            200,
            json={
                "model": "qwen2.5:7b",
                "message": {"role": "assistant", "content": "Hello!"},
                "prompt_eval_count": 5,
                "eval_count": 3,
            },
        )

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.engine.llm._local_provider import OllamaProvider

    provider = OllamaProvider(default_model="qwen2.5:7b")
    result = asyncio.run(provider.chat([{"role": "user", "content": "hi"}]))

    assert result["content"] == "Hello!"
    assert result["model"] == "qwen2.5:7b"
    assert result["provider"] == "ollama"
    assert result["usage"]["prompt_tokens"] == 5
    assert result["usage"]["completion_tokens"] == 3


def test_chat_posts_to_api_chat(isolated_settings, monkeypatch):
    """chat POST 到 /api/chat — Ollama 路由契约"""
    import asyncio

    import httpx

    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(
            200,
            json={"model": "x", "message": {"content": ""}, "prompt_eval_count": 0, "eval_count": 0},
        )

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.engine.llm._local_provider import OllamaProvider

    provider = OllamaProvider(default_model="qwen2.5:7b")
    asyncio.run(provider.chat([{"role": "user", "content": "hi"}]))

    assert captured[0].method == "POST"
    assert captured[0].url.path == "/api/chat"


def test_chat_passes_model_and_options(isolated_settings, monkeypatch):
    """chat body 含 model/messages/stream/options — Ollama 参数契约"""
    import asyncio

    import httpx

    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(
            200,
            json={"model": "x", "message": {"content": ""}, "prompt_eval_count": 0, "eval_count": 0},
        )

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.engine.llm._local_provider import OllamaProvider

    provider = OllamaProvider(default_model="qwen2.5:7b")
    asyncio.run(
        provider.chat(
            [{"role": "user", "content": "hello"}],
            temperature=0.5,
            max_tokens=100,
        )
    )

    body = json.loads(captured[0].content)
    assert body["model"] == "qwen2.5:7b"
    assert body["messages"] == [{"role": "user", "content": "hello"}]
    assert body["stream"] is False
    assert body["options"]["temperature"] == 0.5
    assert body["options"]["num_predict"] == 100


def test_chat_raises_on_http_error(isolated_settings, monkeypatch):
    """Ollama 返回非 200 时抛异常 — 错误透传"""
    import asyncio

    import httpx

    def handler(request):
        return httpx.Response(500, text="Internal Server Error")

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.engine.llm._local_provider import OllamaProvider

    provider = OllamaProvider(default_model="qwen2.5:7b")
    with pytest.raises(RuntimeError, match="500"):
        asyncio.run(provider.chat([{"role": "user", "content": "hi"}]))


# ---------- stream_chat() ----------


def test_stream_chat_yields_content_chunks(isolated_settings, monkeypatch):
    """stream_chat 解析 NDJSON 并 yield content — Ollama 流式协议"""
    import asyncio

    import httpx

    # Ollama NDJSON: 每行一个 JSON 对象, message.content 为内容片段
    ndjson = (
        b'{"model":"x","message":{"content":"Hello"}}\n'
        b'{"model":"x","message":{"content":" world"}}\n'
        b'{"model":"x","message":{"content":"!"}}\n'
    )

    def handler(request):
        return httpx.Response(200, content=ndjson)

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.engine.llm._local_provider import OllamaProvider

    provider = OllamaProvider(default_model="qwen2.5:7b")

    async def collect():
        chunks = []
        async for chunk in provider.stream_chat([{"role": "user", "content": "hi"}]):
            chunks.append(chunk)
        return chunks

    result = asyncio.run(collect())
    assert result == ["Hello", " world", "!"]


def test_stream_chat_skips_empty_lines(isolated_settings, monkeypatch):
    """stream_chat 跳过空行 — 防止 NDJSON 末尾换行导致解析错误"""
    import asyncio

    import httpx

    ndjson = b'{"message":{"content":"a"}}\n\n{"message":{"content":"b"}}\n\n'

    def handler(request):
        return httpx.Response(200, content=ndjson)

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.engine.llm._local_provider import OllamaProvider

    provider = OllamaProvider(default_model="qwen2.5:7b")

    async def collect():
        chunks = []
        async for chunk in provider.stream_chat([{"role": "user", "content": "hi"}]):
            chunks.append(chunk)
        return chunks

    result = asyncio.run(collect())
    assert result == ["a", "b"]


# ---------- list_models() ----------


def test_list_models_returns_model_names(isolated_settings, monkeypatch):
    """list_models 返回模型名列表 — 用户选择模型"""
    import asyncio

    import httpx

    def handler(request):
        return httpx.Response(
            200,
            json={
                "models": [
                    {"name": "qwen2.5:7b"},
                    {"name": "llama3:8b"},
                    {"name": "phi3:mini"},
                ]
            },
        )

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.engine.llm._local_provider import OllamaProvider

    provider = OllamaProvider()
    result = asyncio.run(provider.list_models())
    assert result == ["qwen2.5:7b", "llama3:8b", "phi3:mini"]


def test_list_models_returns_empty_on_connection_error(isolated_settings, monkeypatch):
    """Ollama 未启动时 list_models 返回空列表 (不抛异常) — graceful 降级"""
    import asyncio

    import httpx

    def handler(request):
        raise httpx.ConnectError("Connection refused")

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.engine.llm._local_provider import OllamaProvider

    provider = OllamaProvider()
    result = asyncio.run(provider.list_models())
    assert result == []


# ---------- count_tokens() ----------


def test_count_tokens_estimates_chinese(isolated_settings):
    """中文估算 ~2 token/字 — 与主项目 ollama.py 一致"""
    import asyncio

    from src.engine.llm._local_provider import OllamaProvider

    provider = OllamaProvider()
    # 6 个中文字符 → 6*2 = 12 tokens
    result = asyncio.run(provider.count_tokens("你好世界测试"))
    assert result == 12


def test_count_tokens_estimates_english(isolated_settings):
    """英文估算 ~0.25 token/字符 — 粗略估算"""
    import asyncio

    from src.engine.llm._local_provider import OllamaProvider

    provider = OllamaProvider()
    # 4 个 ASCII 字符 → 4*0.25 = 1 token
    result = asyncio.run(provider.count_tokens("test"))
    assert result == 1
