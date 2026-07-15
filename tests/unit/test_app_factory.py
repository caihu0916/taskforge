
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""P0-18: 开源版启动验证测试

验证:
  - create_app() 返回 FastAPI 实例
  - /health 端点可访问
  - LLMRouter 可实例化 (懒加载)

数据链路: create_app → FastAPI → /health → 200 OK
"""

from __future__ import annotations

import pytest

_TEST_FERNET_KEY = "JHEc0WrVs7NDC7qg8EkQsfZN0UYEqm1twRQHsR5PW9E="


@pytest.fixture
def isolated_settings(monkeypatch, tmp_path):
    """隔离 Settings 单例"""
    from src.infra.config.settings import reset_settings

    reset_settings()
    monkeypatch.setenv("TF_SERVER__ENCRYPTION_KEY", _TEST_FERNET_KEY)
    yield
    reset_settings()


def test_create_app_returns_fastapi_instance(isolated_settings):
    """create_app 返回 FastAPI 实例 — 启动入口契约"""
    from fastapi import FastAPI

    from src.infra.startup.app_factory import create_app

    app = create_app()
    assert isinstance(app, FastAPI)


def test_health_endpoint_returns_200(isolated_settings):
    """/health 端点返回 200 — 服务健康检查"""
    from fastapi.testclient import TestClient

    from src.infra.startup.app_factory import create_app

    app = create_app()
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200


def test_health_endpoint_returns_status_field(isolated_settings):
    """/health 返回 status=ok — 健康检查响应格式"""
    from fastapi.testclient import TestClient

    from src.infra.startup.app_factory import create_app

    app = create_app()
    client = TestClient(app)
    response = client.get("/health")
    data = response.json()
    assert data["status"] == "ok"


def test_app_has_cors_middleware(isolated_settings):
    """app 挂载 CORS 中iddleware — 前端跨域访问前提"""
    from starlette.middleware.cors import CORSMiddleware

    from src.infra.startup.app_factory import create_app

    app = create_app()
    # 检查 middleware 栈中是否有 CORSMiddleware
    middleware_types = [m.cls for m in app.user_middleware]
    assert CORSMiddleware in middleware_types


def test_llm_router_importable(isolated_settings):
    """LLMRouter 可从 _router_core 导入 — 上层调用入口"""
    from src.engine.llm._router_core import LLMRouter

    router = LLMRouter()
    assert router.__class__.__name__ == "LLMRouter"
