
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""P0-09: remote_stubs.py 框架测试 (TDD RED 阶段)

覆盖:
  - get_api_key / set_api_key (追加在 secure_storage.py 末尾)
  - _sign_request (HMAC-SHA256 签名)
  - get_remote_client_config (httpx 客户端基础配置)

数据链路: secure_storage.retrieve → get_api_key → _sign_request → HTTP header
"""
from __future__ import annotations

import hashlib
import hmac
import os

import pytest

# 固定 Fernet key (44 字符 urlsafe base64, 32 字节) — 与主项目 tests/conftest.py 同源
_TEST_FERNET_KEY = "JHEc0WrVs7NDC7qg8EkQsfZN0UYEqm1twRQHsR5PW9E="


@pytest.fixture
def isolated_storage(monkeypatch, tmp_path):
    """隔离 secure_storage: 重定向 ~/.taskforge 到 tmp_path, 注入固定 Fernet key

    同时重置 Settings 单例, 确保 TF_REMOTE__* 等环境变量被重新读取。
    """
    from src.infra.config.settings import reset_settings

    reset_settings()
    monkeypatch.setenv("TF_SERVER__ENCRYPTION_KEY", _TEST_FERNET_KEY)
    monkeypatch.setattr(os.path, "expanduser", lambda _: str(tmp_path))
    yield tmp_path
    reset_settings()


# ---------- P0-09: get_api_key / set_api_key ----------

def test_get_api_key_returns_empty_when_not_set(isolated_storage):
    """未存储时返回空字符串 (而非 None/异常) — 调用方无需 try/except"""
    from src.infra.secure_storage import get_api_key

    assert get_api_key() == ""


def test_set_and_get_api_key_roundtrip(isolated_storage):
    """set_api_key → get_api_key 回路 — 数据链路核心契约"""
    from src.infra.secure_storage import get_api_key, set_api_key

    set_api_key("sk-test-12345")
    assert get_api_key() == "sk-test-12345"


def test_set_api_key_overwrites_previous(isolated_storage):
    """重复 set_api_key 覆盖旧值 — 用户轮换 Key 时必须支持"""
    from src.infra.secure_storage import get_api_key, set_api_key

    set_api_key("sk-old")
    set_api_key("sk-new")
    assert get_api_key() == "sk-new"


# ---------- P0-09: _sign_request ----------

def test_sign_request_returns_hmac_sha256_hex(isolated_storage):
    """_sign_request 返回 HMAC-SHA256 hex (64 字符) — 与服务端验签对齐"""
    from src.infra.remote_stubs import _sign_request

    sig = _sign_request("GET", "/api/v1/test", body=b'{"k":"v"}', secret="my-secret")

    expected = hmac.new(
        b"my-secret",
        b'GET\n/api/v1/test\n{"k":"v"}',
        hashlib.sha256,
    ).hexdigest()
    assert sig == expected
    assert len(sig) == 64


def test_sign_request_deterministic(isolated_storage):
    """相同输入产生相同签名 — 服务端验签前提"""
    from src.infra.remote_stubs import _sign_request

    sig1 = _sign_request("POST", "/api/v1/llm/chat", body=b'{"msg":"hi"}', secret="s")
    sig2 = _sign_request("POST", "/api/v1/llm/chat", body=b'{"msg":"hi"}', secret="s")
    assert sig1 == sig2


def test_sign_request_differs_on_different_body(isolated_storage):
    """不同 body 产生不同签名 — 防篡改核心"""
    from src.infra.remote_stubs import _sign_request

    sig1 = _sign_request("POST", "/api", body=b'{"a":1}', secret="s")
    sig2 = _sign_request("POST", "/api", body=b'{"a":2}', secret="s")
    assert sig1 != sig2


def test_sign_request_accepts_str_body(isolated_storage):
    """body 支持字符串输入 — 调用方便利性"""
    from src.infra.remote_stubs import _sign_request

    sig_str = _sign_request("GET", "/api", body="hello", secret="s")
    sig_bytes = _sign_request("GET", "/api", body=b"hello", secret="s")
    assert sig_str == sig_bytes


# ---------- P0-09: get_remote_client_config ----------

def test_get_remote_client_config_returns_dict(isolated_storage):
    """返回 httpx 客户端配置 dict (含 base_url/timeout) — 桩函数共享配置"""
    from src.infra.remote_stubs import get_remote_client_config

    config = get_remote_client_config()

    assert isinstance(config, dict)
    assert "base_url" in config
    assert "timeout" in config
    assert config["timeout"] > 0


def test_get_remote_client_config_base_url_from_env(monkeypatch, isolated_storage):
    """base_url 从 TF_REMOTE__BASE_URL 读取 — 部署环境可配置"""
    monkeypatch.setenv("TF_REMOTE__BASE_URL", "https://api.example.com")
    from src.infra.remote_stubs import get_remote_client_config

    config = get_remote_client_config()
    assert config["base_url"] == "https://api.example.com"


# ---------- P0-10: remote_llm_chat ----------

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


def test_remote_llm_chat_returns_data_field(isolated_storage, monkeypatch):
    """桩函数返回服务端响应的 data 字段 — 数据链路核心契约"""
    import asyncio

    from src.infra.secure_storage import set_api_key

    set_api_key("sk-test-123")

    def handler(request):
        return __import__("httpx").Response(200, json={"data": {"content": "test"}})

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.infra.remote_stubs import remote_llm_chat

    result = asyncio.run(
        remote_llm_chat(messages=[{"role": "user", "content": "hi"}], model="gpt-4")
    )
    assert result == {"content": "test"}


def test_remote_llm_chat_posts_to_correct_endpoint(isolated_storage, monkeypatch):
    """桩函数 POST 到 /api/v1/llm/chat — 路由契约"""
    import asyncio

    import httpx

    from src.infra.secure_storage import set_api_key

    set_api_key("sk-test-123")

    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(200, json={"data": {"content": "ok"}})

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.infra.remote_stubs import remote_llm_chat

    asyncio.run(
        remote_llm_chat(messages=[{"role": "user", "content": "hi"}], model="gpt-4")
    )

    assert len(captured) == 1
    assert captured[0].method == "POST"
    assert captured[0].url.path == "/api/v1/llm/chat"


def test_remote_llm_chat_sends_signature_header(isolated_storage, monkeypatch):
    """桩函数发送 X-Signature 头 (HMAC 签名) — 服务端验签前提"""
    import asyncio

    import httpx

    from src.infra.secure_storage import set_api_key

    set_api_key("sk-test-123")

    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(200, json={"data": {}})

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.infra.remote_stubs import remote_llm_chat

    asyncio.run(
        remote_llm_chat(messages=[{"role": "user", "content": "hi"}], model="gpt-4")
    )

    assert "x-signature" in {k.lower() for k in captured[0].headers}
    assert len(captured[0].headers["x-signature"]) == 64  # HMAC-SHA256 hex


def test_remote_llm_chat_sends_api_key_header(isolated_storage, monkeypatch):
    """桩函数发送 X-API-Key 头 — 服务端身份识别"""
    import asyncio

    import httpx

    from src.infra.secure_storage import set_api_key

    set_api_key("sk-test-123")

    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(200, json={"data": {}})

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.infra.remote_stubs import remote_llm_chat

    asyncio.run(
        remote_llm_chat(messages=[{"role": "user", "content": "hi"}], model="gpt-4")
    )

    headers = {k.lower(): v for k, v in captured[0].headers.items()}
    assert headers.get("x-api-key") == "sk-test-123"


def test_remote_llm_chat_raises_without_api_key(isolated_storage, monkeypatch):
    """未配置 API Key 时抛 RuntimeError — 调用方需先登录"""
    import asyncio

    def handler(request):
        return __import__("httpx").Response(200, json={"data": {}})

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.infra.remote_stubs import remote_llm_chat

    with pytest.raises(RuntimeError, match="API Key"):
        asyncio.run(
            remote_llm_chat(messages=[{"role": "user", "content": "hi"}], model="gpt-4")
        )


def test_remote_llm_chat_sends_request_body(isolated_storage, monkeypatch):
    """桩函数在 body 中传递 messages/model/temperature/max_tokens — 参数契约"""
    import asyncio
    import json

    import httpx

    from src.infra.secure_storage import set_api_key

    set_api_key("sk-test-123")

    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(200, json={"data": {}})

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.infra.remote_stubs import remote_llm_chat

    asyncio.run(
        remote_llm_chat(
            messages=[{"role": "user", "content": "hello"}],
            model="gpt-4",
            temperature=0.5,
            max_tokens=100,
        )
    )

    body = json.loads(captured[0].content)
    assert body["messages"] == [{"role": "user", "content": "hello"}]
    assert body["model"] == "gpt-4"
    assert body["temperature"] == 0.5
    assert body["max_tokens"] == 100


def test_remote_llm_chat_raises_on_http_error(isolated_storage, monkeypatch):
    """服务端返回非 200 时抛 RuntimeError — 错误透传"""
    import asyncio

    import httpx

    from src.infra.secure_storage import set_api_key

    set_api_key("sk-test-123")

    def handler(request):
        return httpx.Response(500, text="Internal Server Error")

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.infra.remote_stubs import remote_llm_chat

    with pytest.raises(RuntimeError, match="500"):
        asyncio.run(
            remote_llm_chat(messages=[{"role": "user", "content": "hi"}], model="gpt-4")
        )


# ---------- P0-11: remote_llm_stream (SSE 代理) ----------

def _collect_stream(coro):
    """辅助: 收集 async generator 的所有 yield"""
    import asyncio

    async def _collect():
        chunks = []
        async for chunk in await coro:
            chunks.append(chunk)
        return chunks

    return asyncio.run(_collect())


def test_remote_llm_stream_yields_data_chunks(isolated_storage, monkeypatch):
    """桩函数正确 yield SSE 数据块 (去掉 'data: ' 前缀)"""
    import httpx

    from src.infra.secure_storage import set_api_key

    set_api_key("sk-test-123")

    sse_content = b"data: chunk1\n\ndata: chunk2\n\ndata: chunk3\n\n"

    def handler(request):
        return httpx.Response(
            200,
            content=sse_content,
            headers={"content-type": "text/event-stream"},
        )

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.infra.remote_stubs import remote_llm_stream

    async def collect():
        chunks = []
        async for chunk in remote_llm_stream(
            messages=[{"role": "user", "content": "hi"}], model="gpt-4"
        ):
            chunks.append(chunk)
        return chunks

    import asyncio

    result = asyncio.run(collect())
    assert result == ["chunk1", "chunk2", "chunk3"]


def test_remote_llm_stream_skips_keepalive_comments(isolated_storage, monkeypatch):
    """桩函数跳过 SSE 注释行 (: 开头的 keepalive)"""
    import asyncio

    import httpx

    from src.infra.secure_storage import set_api_key

    set_api_key("sk-test-123")

    # SSE: 注释行 (: ping) 应被跳过
    sse_content = b"data: a\n\n: keepalive\n\ndata: b\n\n"

    def handler(request):
        return httpx.Response(200, content=sse_content, headers={"content-type": "text/event-stream"})

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.infra.remote_stubs import remote_llm_stream

    async def collect():
        chunks = []
        async for chunk in remote_llm_stream(messages=[{"role": "user", "content": "hi"}]):
            chunks.append(chunk)
        return chunks

    result = asyncio.run(collect())
    assert result == ["a", "b"]


def test_remote_llm_stream_posts_to_correct_endpoint(isolated_storage, monkeypatch):
    """桩函数 POST 到 /api/v1/llm/stream — 路由契约"""
    import asyncio

    import httpx

    from src.infra.secure_storage import set_api_key

    set_api_key("sk-test-123")

    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(200, content=b"data: ok\n\n", headers={"content-type": "text/event-stream"})

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.infra.remote_stubs import remote_llm_stream

    async def consume():
        async for _ in remote_llm_stream(messages=[{"role": "user", "content": "hi"}]):
            pass

    asyncio.run(consume())

    assert len(captured) == 1
    assert captured[0].method == "POST"
    assert captured[0].url.path == "/api/v1/llm/stream"


def test_remote_llm_stream_raises_without_api_key(isolated_storage, monkeypatch):
    """未配置 API Key 时抛 RuntimeError"""
    import asyncio

    import httpx

    def handler(request):
        return httpx.Response(200, content=b"data: ok\n\n", headers={"content-type": "text/event-stream"})

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.infra.remote_stubs import remote_llm_stream

    async def consume():
        async for _ in remote_llm_stream(messages=[{"role": "user", "content": "hi"}]):
            pass

    with pytest.raises(RuntimeError, match="API Key"):
        asyncio.run(consume())


def test_remote_llm_stream_sends_signature_header(isolated_storage, monkeypatch):
    """桩函数发送 X-Signature 头"""
    import asyncio

    import httpx

    from src.infra.secure_storage import set_api_key

    set_api_key("sk-test-123")

    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(200, content=b"data: ok\n\n", headers={"content-type": "text/event-stream"})

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.infra.remote_stubs import remote_llm_stream

    async def consume():
        async for _ in remote_llm_stream(messages=[{"role": "user", "content": "hi"}]):
            pass

    asyncio.run(consume())

    assert len(captured[0].headers["x-signature"]) == 64


# ---------- P0-12: remote_template_download ----------

def test_remote_template_download_returns_template(isolated_storage, monkeypatch):
    """桩函数返回模板配置 dict"""
    import asyncio

    import httpx

    from src.infra.secure_storage import set_api_key

    set_api_key("sk-test-123")

    template_data = {"id": "tpl-001", "name": "小红书内容", "phases": []}

    def handler(request):
        return httpx.Response(200, json={"data": template_data})

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.infra.remote_stubs import remote_template_download

    result = asyncio.run(remote_template_download("tpl-001"))
    assert result == template_data


def test_remote_template_download_uses_get_method(isolated_storage, monkeypatch):
    """桩函数用 GET 方法请求 /api/v1/templates/{id}/download"""
    import asyncio

    import httpx

    from src.infra.secure_storage import set_api_key

    set_api_key("sk-test-123")

    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(200, json={"data": {}})

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.infra.remote_stubs import remote_template_download

    asyncio.run(remote_template_download("tpl-001"))

    assert captured[0].method == "GET"
    assert captured[0].url.path == "/api/v1/templates/tpl-001/download"


def test_remote_template_download_raises_without_api_key(isolated_storage, monkeypatch):
    """未配置 API Key 时抛 RuntimeError"""
    import asyncio

    import httpx

    def handler(request):
        return httpx.Response(200, json={"data": {}})

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.infra.remote_stubs import remote_template_download

    with pytest.raises(RuntimeError, match="API Key"):
        asyncio.run(remote_template_download("tpl-001"))


# ---------- P0-13: remote_auth_login ----------

def test_remote_auth_login_returns_api_key(isolated_storage, monkeypatch):
    """桩函数返回服务端签发的 API Key"""
    import asyncio

    import httpx

    def handler(request):
        return httpx.Response(200, json={"data": {"api_key": "sk-server-issued-123"}})

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.infra.remote_stubs import remote_auth_login

    result = asyncio.run(remote_auth_login("user@example.com", "pass123"))
    assert result == "sk-server-issued-123"


def test_remote_auth_login_posts_credentials(isolated_storage, monkeypatch):
    """桩函数 POST email/password 到 /api/v1/auth/login"""
    import asyncio
    import json

    import httpx

    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(200, json={"data": {"api_key": "sk-123"}})

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.infra.remote_stubs import remote_auth_login

    asyncio.run(remote_auth_login("user@example.com", "pass123"))

    assert captured[0].method == "POST"
    assert captured[0].url.path == "/api/v1/auth/login"
    body = json.loads(captured[0].content)
    assert body["email"] == "user@example.com"
    assert body["password"] == "pass123"


def test_remote_auth_login_persists_api_key(isolated_storage, monkeypatch):
    """登录成功后自动持久化 API Key 到 secure_storage — 数据链路核心"""
    import asyncio

    import httpx

    def handler(request):
        return httpx.Response(200, json={"data": {"api_key": "sk-persisted-456"}})

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.infra.remote_stubs import remote_auth_login

    from src.infra.secure_storage import get_api_key

    asyncio.run(remote_auth_login("user@example.com", "pass123"))

    # 后续调用 get_api_key 应返回登录获取的 key
    assert get_api_key() == "sk-persisted-456"


def test_remote_auth_login_raises_on_http_error(isolated_storage, monkeypatch):
    """服务端返回非 200 时抛 RuntimeError"""
    import asyncio

    import httpx

    def handler(request):
        return httpx.Response(401, text="Invalid credentials")

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.infra.remote_stubs import remote_auth_login

    with pytest.raises(RuntimeError, match="401"):
        asyncio.run(remote_auth_login("user@example.com", "wrong"))


# ---------- P0-14: remote_scene_execute ----------

def test_remote_scene_execute_returns_result(isolated_storage, monkeypatch):
    """桩函数返回场景执行结果"""
    import asyncio

    import httpx

    from src.infra.secure_storage import set_api_key

    set_api_key("sk-test-123")

    scene_result = {"status": "success", "output": "内容已生成"}

    def handler(request):
        return httpx.Response(200, json={"data": scene_result})

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.infra.remote_stubs import remote_scene_execute

    result = asyncio.run(
        remote_scene_execute("xiaohongshu", {"action": "write", "topic": "测试"})
    )
    assert result == scene_result


def test_remote_scene_execute_posts_to_correct_endpoint(isolated_storage, monkeypatch):
    """桩函数 POST 到 /api/v1/scenes/{type}/execute"""
    import asyncio

    import httpx

    from src.infra.secure_storage import set_api_key

    set_api_key("sk-test-123")

    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(200, json={"data": {}})

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.infra.remote_stubs import remote_scene_execute

    asyncio.run(remote_scene_execute("finance", {"action": "report"}))

    assert captured[0].method == "POST"
    assert captured[0].url.path == "/api/v1/scenes/finance/execute"


def test_remote_scene_execute_raises_without_api_key(isolated_storage, monkeypatch):
    """未配置 API Key 时抛 RuntimeError"""
    import asyncio

    import httpx

    def handler(request):
        return httpx.Response(200, json={"data": {}})

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.infra.remote_stubs import remote_scene_execute

    with pytest.raises(RuntimeError, match="API Key"):
        asyncio.run(remote_scene_execute("xiaohongshu", {}))


# ---------- P0-15: remote_usage_query ----------

def test_remote_usage_query_returns_usage(isolated_storage, monkeypatch):
    """桩函数返回用量 dict"""
    import asyncio

    import httpx

    from src.infra.secure_storage import set_api_key

    set_api_key("sk-test-123")

    usage_data = {"tokens_used": 50000, "tokens_limit": 100000, "plan": "pro"}

    def handler(request):
        return httpx.Response(200, json={"data": usage_data})

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.infra.remote_stubs import remote_usage_query

    result = asyncio.run(remote_usage_query())
    assert result == usage_data


def test_remote_usage_query_uses_get_method(isolated_storage, monkeypatch):
    """桩函数用 GET 方法请求 /api/v1/usage"""
    import asyncio

    import httpx

    from src.infra.secure_storage import set_api_key

    set_api_key("sk-test-123")

    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(200, json={"data": {}})

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.infra.remote_stubs import remote_usage_query

    asyncio.run(remote_usage_query())

    assert captured[0].method == "GET"
    assert captured[0].url.path == "/api/v1/usage"


def test_remote_usage_query_raises_without_api_key(isolated_storage, monkeypatch):
    """未配置 API Key 时抛 RuntimeError"""
    import asyncio

    import httpx

    def handler(request):
        return httpx.Response(200, json={"data": {}})

    _patch_httpx_with_mock(monkeypatch, handler)

    from src.infra.remote_stubs import remote_usage_query

    with pytest.raises(RuntimeError, match="API Key"):
        asyncio.run(remote_usage_query())
