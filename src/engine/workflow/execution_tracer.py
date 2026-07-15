
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""ExecutionTracer — 工作流执行追踪器(P1-S1-021)

记录工作流执行的完整轨迹,支持:
  - 节点级 trace(开始/结束/状态/输入/输出/耗时)
  - 边级 trace(数据流向)
  - trace_id 贯穿(对接 INF-011 可观测性)
  - trace 持久化(SQLite/JSON)
  - trace 查询与回放(对接 P1-S1-023 工作流历史)

设计原则:
  - 零侵入: 通过 BaseExecutor.execute_with_trace 自动采集
  - 可选: 不配置 tracer 时无性能开销
  - 结构化: 每条 trace 记录为 Span(类 OpenTelemetry)
"""

from __future__ import annotations

import json
import time
import uuid as _uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# ── 数据模型 ──


@dataclass
class TraceSpan:
    """追踪 Span(单个节点的执行记录)"""

    span_id: str = field(default_factory=lambda: _uuid.uuid4().hex[:16])
    trace_id: str = ""
    parent_span_id: str = ""
    node_id: str = ""
    node_type: str = ""
    run_id: str = ""
    status: str = "submitted"  # A2A 五态
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0
    duration_ms: float = 0.0
    input_data: dict[str, Any] = field(default_factory=dict)
    output_data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    def finish(self, status: str, output: dict[str, Any] | None = None, error: str = "") -> None:
        """结束 span"""
        self.end_time = time.time()
        self.duration_ms = (self.end_time - self.start_time) * 1000
        self.status = status
        if output:
            self.output_data = output
        if error:
            self.error = error

    def add_event(self, name: str, payload: dict[str, Any] | None = None) -> None:
        """添加事件(如状态转换)"""
        self.events.append(
            {
                "name": name,
                "timestamp": time.time(),
                "payload": payload or {},
            }
        )

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典"""
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_span_id": self.parent_span_id,
            "node_id": self.node_id,
            "node_type": self.node_type,
            "run_id": self.run_id,
            "status": self.status,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": round(self.duration_ms, 2),
            "input_data": self.input_data,
            "output_data": self.output_data,
            "error": self.error,
            "metadata": self.metadata,
            "events": self.events,
        }


@dataclass
class WorkflowTrace:
    """工作流执行轨迹(包含多个 span)"""

    trace_id: str = field(default_factory=lambda: _uuid.uuid4().hex[:16])
    run_id: str = ""
    workflow_name: str = ""
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0
    duration_ms: float = 0.0
    status: str = "running"
    spans: list[TraceSpan] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_span(self, span: TraceSpan) -> None:
        span.trace_id = self.trace_id
        if not span.run_id:
            span.run_id = self.run_id
        self.spans.append(span)

    def finish(self, status: str = "completed") -> None:
        """结束 trace"""
        self.end_time = time.time()
        self.duration_ms = (self.end_time - self.start_time) * 1000
        self.status = status

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "run_id": self.run_id,
            "workflow_name": self.workflow_name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": round(self.duration_ms, 2),
            "status": self.status,
            "span_count": len(self.spans),
            "spans": [s.to_dict() for s in self.spans],
            "metadata": self.metadata,
        }


# ── ExecutionTracer ──


class ExecutionTracer:
    """工作流执行追踪器

    用法:
        tracer = ExecutionTracer(persistence_dir="data/traces")
        trace = tracer.start_trace(run_id="r1", workflow_name="my_wf")

        #节点执行前
        span = tracer.start_span(
            trace_id=trace.trace_id,
            node_id="n1",
            node_type="http_request",
            input_data={"url": "https://api.example.com"},
        )

        #节点执行后
        tracer.finish_span(span, status="completed", output={"status_code": 200})

        #结束 trace
        tracer.finish_trace(trace, status="completed")

        #查询
        loaded = tracer.load_trace(trace.trace_id)
    """

    def __init__(self, persistence_dir: str = "") -> None:
        self._persistence_dir = Path(persistence_dir) if persistence_dir else None
        if self._persistence_dir:
            self._persistence_dir.mkdir(parents=True, exist_ok=True)
        self._active_traces: dict[str, WorkflowTrace] = {}
        self._active_spans: dict[str, TraceSpan] = {}
        self.logger = structlog.get_logger(__name__).bind(component="ExecutionTracer")

    # ── Trace 生命周期 ──

    def start_trace(
        self,
        run_id: str = "",
        workflow_name: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> WorkflowTrace:
        """开始工作流 trace"""
        trace = WorkflowTrace(run_id=run_id, workflow_name=workflow_name)
        if metadata:
            trace.metadata = metadata
        self._active_traces[trace.trace_id] = trace
        self.logger.info(
            "trace_started",
            trace_id=trace.trace_id,
            run_id=run_id,
            workflow_name=workflow_name,
        )
        return trace

    def finish_trace(
        self,
        trace: WorkflowTrace,
        status: str = "completed",
    ) -> None:
        """结束工作流 trace 并持久化"""
        trace.finish(status)
        self._persist_trace(trace)
        self._active_traces.pop(trace.trace_id, None)
        self.logger.info(
            "trace_finished",
            trace_id=trace.trace_id,
            status=status,
            span_count=len(trace.spans),
            duration_ms=round(trace.duration_ms, 2),
        )

    # ── Span 生命周期 ──

    def start_span(
        self,
        trace_id: str,
        node_id: str,
        node_type: str,
        input_data: dict[str, Any] | None = None,
        parent_span_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> TraceSpan:
        """开始节点 span"""
        span = TraceSpan(
            trace_id=trace_id,
            node_id=node_id,
            node_type=node_type,
            input_data=input_data or {},
            parent_span_id=parent_span_id,
        )
        if metadata:
            span.metadata = metadata

        trace = self._active_traces.get(trace_id)
        if trace:
            trace.add_span(span)

        self._active_spans[span.span_id] = span
        self.logger.debug(
            "span_started",
            span_id=span.span_id,
            trace_id=trace_id,
            node_id=node_id,
            node_type=node_type,
        )
        return span

    def finish_span(
        self,
        span: TraceSpan,
        status: str = "completed",
        output: dict[str, Any] | None = None,
        error: str = "",
    ) -> None:
        """结束节点 span"""
        span.finish(status=status, output=output, error=error)
        self._active_spans.pop(span.span_id, None)
        self.logger.debug(
            "span_finished",
            span_id=span.span_id,
            node_id=span.node_id,
            status=status,
            duration_ms=round(span.duration_ms, 2),
        )

    def add_span_event(
        self,
        span: TraceSpan,
        event_name: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """为 span 添加事件"""
        span.add_event(event_name, payload)

    # ── 查询 ──

    def get_trace(self, trace_id: str) -> WorkflowTrace | None:
        """获取活跃 trace(内存中)"""
        return self._active_traces.get(trace_id)

    def load_trace(self, trace_id: str) -> WorkflowTrace | None:
        """从持久化存储加载 trace"""
        if not self._persistence_dir:
            return None
        trace_file = self._persistence_dir / f"{trace_id}.json"
        if not trace_file.exists():
            return None
        try:
            data = json.loads(trace_file.read_text(encoding="utf-8"))
            trace = WorkflowTrace(
                trace_id=data["trace_id"],
                run_id=data.get("run_id", ""),
                workflow_name=data.get("workflow_name", ""),
                start_time=data.get("start_time", 0),
                end_time=data.get("end_time", 0),
                duration_ms=data.get("duration_ms", 0),
                status=data.get("status", "completed"),
                metadata=data.get("metadata", {}),
            )
            for span_data in data.get("spans", []):
                span = TraceSpan(
                    span_id=span_data["span_id"],
                    trace_id=span_data.get("trace_id", trace.trace_id),
                    parent_span_id=span_data.get("parent_span_id", ""),
                    node_id=span_data.get("node_id", ""),
                    node_type=span_data.get("node_type", ""),
                    run_id=span_data.get("run_id", ""),
                    status=span_data.get("status", "completed"),
                    start_time=span_data.get("start_time", 0),
                    end_time=span_data.get("end_time", 0),
                    duration_ms=span_data.get("duration_ms", 0),
                    input_data=span_data.get("input_data", {}),
                    output_data=span_data.get("output_data", {}),
                    error=span_data.get("error", ""),
                    metadata=span_data.get("metadata", {}),
                    events=span_data.get("events", []),
                )
                trace.spans.append(span)
            return trace
        except Exception as e:
            self.logger.error("trace_load_failed", trace_id=trace_id, error=str(e))
            return None

    def list_traces(self, limit: int = 50) -> list[dict[str, Any]]:
        """列出最近的 trace(从持久化存储)"""
        if not self._persistence_dir:
            return []
        traces = []
        for trace_file in sorted(
            self._persistence_dir.glob("*.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )[:limit]:
            try:
                data = json.loads(trace_file.read_text(encoding="utf-8"))
                traces.append(
                    {
                        "trace_id": data.get("trace_id"),
                        "run_id": data.get("run_id"),
                        "workflow_name": data.get("workflow_name"),
                        "status": data.get("status"),
                        "start_time": data.get("start_time"),
                        "duration_ms": data.get("duration_ms"),
                        "span_count": len(data.get("spans", [])),
                    }
                )
            except Exception as exc:
                logger.debug("exception_handled", error=str(exc))
                continue
        return traces

    # ── 持久化 ──

    def _persist_trace(self, trace: WorkflowTrace) -> None:
        """持久化 trace 到 JSON 文件"""
        if not self._persistence_dir:
            return
        trace_file = self._persistence_dir / f"{trace.trace_id}.json"
        try:
            trace_file.write_text(
                json.dumps(trace.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            self.logger.error("trace_persist_failed", trace_id=trace.trace_id, error=str(e))


# ── 全局单例 ──

_global_tracer: ExecutionTracer | None = None


def get_execution_tracer() -> ExecutionTracer:
    """获取全局 ExecutionTracer 单例"""
    global _global_tracer
    if _global_tracer is None:
        _global_tracer = ExecutionTracer(persistence_dir="data/traces")
    return _global_tracer


def set_execution_tracer(tracer: ExecutionTracer) -> None:
    """设置全局 ExecutionTracer(用于测试)"""
    global _global_tracer
    _global_tracer = tracer


def reset_execution_tracer() -> None:
    """重置全局 ExecutionTracer 单例"""
    global _global_tracer
    _global_tracer = None
