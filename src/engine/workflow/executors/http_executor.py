
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""HttpRequest 节点执行器(P1-S1-003)

发起 HTTP 请求,支持 GET/POST/PUT/DELETE/PATCH。
"""

from __future__ import annotations

from typing import Any

import structlog

from . import BaseExecutor, NodeInput, NodeOutput, register_executor

logger = structlog.get_logger(__name__)


@register_executor("http_request")
class HttpRequestExecutor(BaseExecutor):
    """HTTP 请求执行器

    配置:
        url: 请求 URL(必填)
        method: HTTP 方法(默认 GET)
        headers: 请求头(可选)
        body: 请求体(可选,POST/PUT 用)
        timeout: 超时秒数(默认 30)
    """

    node_type = "http_request"
    config_schema = {
        "url": {"required": True, "type": "string"},
        "method": {"required": False, "type": "string", "default": "GET"},
        "headers": {"required": False, "type": "object", "default": {}},
        "body": {"required": False, "type": "any", "default": None},
        "timeout": {"required": False, "type": "number", "default": 30},
    }

    async def execute(self, inp: NodeInput) -> NodeOutput:
        import httpx

        url = inp.config.get("url", "")
        method = inp.config.get("method", "GET").upper()
        headers = inp.config.get("headers", {})
        body = inp.config.get("body")
        timeout = inp.config.get("timeout", 30)

        if not url:
            return NodeOutput(
                node_id=inp.node_id,
                status="failed",
                error="url is required",
            )

        # 支持上下文变量替换 {{var}}
        url = self._interpolate(url, inp.context)
        if isinstance(body, str):
            body = self._interpolate(body, inp.context)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                req_kwargs: dict[str, Any] = {"headers": headers}
                if body is not None and method in ("POST", "PUT", "PATCH"):
                    if isinstance(body, (dict, list)):
                        req_kwargs["json"] = body
                    else:
                        req_kwargs["content"] = str(body)

                response = await client.request(method, url, **req_kwargs)

                return NodeOutput(
                    node_id=inp.node_id,
                    status="completed",
                    output={
                        "status_code": response.status_code,
                        "headers": dict(response.headers),
                        "body": response.text,
                        "json": self._try_parse_json(response.text),
                        "url": str(response.url),
                        "elapsed_ms": response.elapsed.total_seconds() * 1000,
                    },
                )
        except httpx.TimeoutException:
            return NodeOutput(
                node_id=inp.node_id,
                status="failed",
                error=f"HTTP request timeout after {timeout}s",
            )
        except Exception as e:
            return NodeOutput(
                node_id=inp.node_id,
                status="failed",
                error=f"HTTP request failed: {e}",
            )

    def _interpolate(self, text: str, context: dict[str, Any]) -> str:
        """上下文变量替换 {{var}} → context[var]"""
        if not context:
            return text
        result = text
        for key, value in context.items():
            result = result.replace(f"{{{{{key}}}}}", str(value))
        return result

    def _try_parse_json(self, text: str) -> Any:
        """尝试解析 JSON,失败返回 None"""
        try:
            import json

            return json.loads(text)
        except Exception:
            return None
