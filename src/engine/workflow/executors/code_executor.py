
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Code 节点执行器(P1-S1-009) — 沙箱安全执行用户代码

P0-2 AGENT-001 修复要点:
  1. 删除重复定义的 _execute_sandboxed（原 211-245 行无超时版本）
  2. 扩充 FORBIDDEN_BUILTINS：加入 getattr/setattr/delattr/type/object/super 等
  3. AST 检查扩展：委托 _sandbox_config._CodeValidator（拦截 dunder 字符串字面量访问）
  4. 运行时沙箱：使用 _SAFE_BUILTINS + _restricted_import（与 code_execute 工具同源）
  5. 超时保护：Windows 兼容的 threading daemon 方案（SIGALRM 仅 Unix）
  6. 沙箱违规记录 sandbox_escape_blocked 日志

RCE 沙箱缺陷修复 (阻塞级):
  - 废弃进程内 exec()（即使在 daemon thread 中也不安全）
  - 改为子进程沙箱执行（subprocess.Popen + 资源限制 + 超时）
  - 复用 code_execute 工具同源沙箱: _SANDBOX_HEADER + _apply_resource_limits_windows + get_linux_preexec_fn
  - AST 验证作为第一道防线（子进程执行前先过 AST 验证）
  - AGENT-016: hard_limits 校验代码执行超时上限
"""

from __future__ import annotations

import ast
import contextlib
import json
import os
import platform
import subprocess
import sys
import tempfile
from typing import Any

import structlog

from config import get_settings
from src.engine.tool.builtin._sandbox_config import (
    _SANDBOX_HEADER,
    _apply_resource_limits_windows,
    _CodeValidator,
    get_linux_preexec_fn,
    has_rlimit_support,
)
from src.exceptions import ErrorCode, TaskForgeError

from . import BaseExecutor, NodeInput, NodeOutput, register_executor

logger = structlog.get_logger(__name__)

# 禁止的模块(沙箱安全) — 与 _sandbox_config._FORBIDDEN 对齐
FORBIDDEN_MODULES = {
    "socket",
    "subprocess",
    "os",
    "sys",
    "shutil",
    "ctypes",
    "multiprocessing",
    "asyncio",
    "threading",
    "signal",
    "fcntl",
    "resource",
    "pathlib",
    "pickle",
    "marshal",
    "http",
    "urllib",
    "requests",
    "importlib",
    "inspect",
}

# 禁止的内置函数 — P0-2 扩充：覆盖所有可导致逃逸的内省/动态执行 builtin
FORBIDDEN_BUILTINS = {
    "exec",
    "eval",
    "compile",
    "open",
    "input",
    "__import__",
    "globals",
    "locals",
    "vars",
    "dir",
    # P0-2 新增：属性内省族 — 可绕过 AST 拦截访问 dunder
    "getattr",
    "setattr",
    "delattr",
    "hasattr",
    # P0-2 新增：类型系统族 — 可动态创建类触发 __init__ 逃逸
    "type",
    "object",
    "super",
    "classmethod",
    "staticmethod",
    "property",
    # P0-2 新增：内存/字节族 — 可构造任意字节缓冲
    "memoryview",
    "bytearray",
    "bytes",
    # P0-2 新增：交互族
    "breakpoint",
    "exit",
    "quit",
}


class CodeExecutionTimeout(TaskForgeError):
    default_code = ErrorCode.WF_CODE_TIMEOUT
    """代码执行超时异常"""


def _timeout_handler(signum, frame):  # pragma: no cover - Unix SIGALRM 回退路径
    """超时信号处理器（仅 Unix 系统回退使用）"""
    raise CodeExecutionTimeout("Code execution timed out")


@register_executor("code")
class CodeExecutor(BaseExecutor):
    """代码节点执行器(沙箱)

    配置:
        code: 要执行的 Python 代码(必填)
        language: 语言(仅支持 python,默认 python)
        timeout: 执行超时秒数(默认 10)
        entry_function: 入口函数名(默认 main)
    """

    node_type = "code"
    config_schema = {
        "code": {"required": True, "type": "string"},
        "language": {"required": False, "type": "string", "default": "python"},
        "timeout": {"required": False, "type": "number", "default": 10},
        "entry_function": {"required": False, "type": "string", "default": "main"},
    }

    async def execute(self, inp: NodeInput) -> NodeOutput:
        code = inp.config.get("code", "")
        language = inp.config.get("language", "python")
        entry_fn = inp.config.get("entry_function", "main")
        timeout = inp.config.get("timeout", 10)

        if not code:
            return NodeOutput(
                node_id=inp.node_id,
                status="failed",
                error="code is required",
            )

        if language != "python":
            return NodeOutput(
                node_id=inp.node_id,
                status="failed",
                error=f"Unsupported language: {language} (only python supported)",
            )

        # 沙箱安全检查（AST 静态分析 — 第一道防线）
        safety_check = self._check_safety(code)
        if safety_check:
            logger.warning(
                "sandbox_escape_blocked",
                node_id=inp.node_id,
                violation=safety_check,
                code_preview=code[:200],
            )
            return NodeOutput(
                node_id=inp.node_id,
                status="failed",
                error=f"Sandbox safety violation: {safety_check}",
            )

        # AGENT-016: hard_limits 校验 — 代码执行超时上限
        try:
            from src.engine.agent.hard_limits import get_hard_limits

            _hl = get_hard_limits()
            _max_exec_time = _hl.get("agent_safety", "max_code_execution_time")
            if _max_exec_time is not None:
                _hl_result = _hl.check("agent_safety", "max_code_execution_time", timeout)
                if not _hl_result.passed and _hl.should_block(_hl_result):
                    logger.warning(
                        "hard_limit_blocked_code_execution",
                        node_id=inp.node_id,
                        timeout=timeout,
                        limit=_max_exec_time,
                        message=_hl_result.message,
                    )
                    return NodeOutput(
                        node_id=inp.node_id,
                        status="failed",
                        error=f"Hard limit violated: {_hl_result.message}",
                    )
        except Exception as exc:
            logger.debug("exception_handled", error=str(exc))
            # hard_limits 不可用时降级，不阻断执行
            logger.debug("hard_limits_check_unavailable", exc_info=True)

        # 执行代码（子进程沙箱 — 第二道防线；超时保护）
        try:
            result = self._execute_sandboxed(code, entry_fn, inp.context, timeout)
            return NodeOutput(
                node_id=inp.node_id,
                status="completed",
                output={
                    "result": result,
                    "language": language,
                    "entry_function": entry_fn,
                },
            )
        except CodeExecutionTimeout:
            return NodeOutput(
                node_id=inp.node_id,
                status="failed",
                error=f"Code execution timed out after {timeout}s",
            )
        except Exception as e:
            return NodeOutput(
                node_id=inp.node_id,
                status="failed",
                error=f"Code execution failed: {type(e).__name__}: {e}",
            )

    def _check_safety(self, code: str) -> str | None:
        """沙箱安全检查（静态 AST 分析）

        委托 _sandbox_config._CodeValidator（与 code_execute 工具同源验证器），
        覆盖: 危险 import / blocked name 调用 / dunder 属性访问 / 字符串拼接构造危险名。

        返回 None=安全, string=违规描述
        """
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return f"Syntax error: {e}"

        validator = _CodeValidator()
        validator.visit(tree)
        if validator.errors:
            return "; ".join(validator.errors)

        # 额外检查：ast.Call 中以字符串字面量作参数的 dunder 访问
        # （如 getattr(x, '__class__') — _CodeValidator 已拦截 getattr 调用，
        # 此处为纵深防御，拦截任何将 dunder 字符串作为参数的调用）
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for arg in node.args:
                    if (
                        isinstance(arg, ast.Constant)
                        and isinstance(arg.value, str)
                        and arg.value.startswith("__")
                        and arg.value.endswith("__")
                    ):
                        return f"String literal dunder access blocked: {arg.value}"

        return None

    def _execute_sandboxed(self, code: str, entry_fn: str, context: dict[str, Any], timeout: int = 10) -> Any:
        """在子进程沙箱中执行代码（废弃进程内 exec）

        RCE 沙箱缺陷修复:
          - 不再用 exec(code, safe_globals) 在主进程内执行（即使在 daemon thread 中也不安全）
          - 改为 subprocess.Popen 子进程执行，与 code_execute 工具同源沙箱

        安全措施:
          1. AST 验证（execute() 入口已做）— 第一道防线
          2. 子进程隔离（subprocess.Popen + -S 禁用 site 模块）
          3. _SANDBOX_HEADER 注入受限 __builtins__（替换 __import__/getattr/setattr/delattr）
          4. 资源限制: Linux setrlimit（内存/CPU/进程数）/ Windows Job Object（内存）
          5. 超时: proc.communicate(timeout) + proc.kill()
        """
        max_output = 100_000

        # 序列化 context 供子进程使用（JSON 安全序列化，非可序列化对象降级为字符串）
        try:
            context_json = json.dumps(context, default=str, ensure_ascii=False)
        except (TypeError, ValueError):
            context_json = "{}"

        # 校验 entry_fn 为安全标识符（防止注入）
        safe_entry_fn = entry_fn if entry_fn and entry_fn.isidentifier() else "main"

        # 构建子进程执行的完整代码: 沙箱头 + context 注入 + 用户代码 + 结果捕获 epilogue
        wrapper = (
            _SANDBOX_HEADER
            + "\n# TaskForge CodeExecutor subprocess wrapper\n"
            + "import json as _tf_ctx_json\n"
            + "try:\n"
            + "    context = _tf_ctx_json.loads("
            + repr(context_json)
            + ")\n"
            + "except Exception:\n"
            + "    context = {}\n"
            + "result = None\n"
            + "\n# === USER CODE START ===\n"
            + code
            + "\n# === USER CODE END ===\n"
            + "\n# Result capture epilogue\n"
            + "import json as _tf_result_json\n"
            + "_tf_final = None\n"
            + "try:\n"
            + "    if '"
            + safe_entry_fn
            + "' in dir() and callable("
            + safe_entry_fn
            + "):\n"
            + "        _tf_final = "
            + safe_entry_fn
            + "(context)\n"
            + "    elif 'result' in dir():\n"
            + "        _tf_final = result\n"
            + "except Exception as _e:\n"
            + "    print('__TF_ERROR__' + repr(_e))\n"
            + "    raise\n"
            + "print('__TF_RESULT__' + _tf_result_json.dumps(_tf_final, default=str))\n"
        )

        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".py",
                delete=False,
                encoding="utf-8",
                dir=get_settings().server.sandbox_tmp_dir or None,
            ) as tmp:
                tmp.write(wrapper)
                tmp_path = tmp.name

            # 安全执行: 最小化环境变量，禁用 site 模块
            # Windows 上必须保留 SystemRoot/PATH/TEMP 等，否则子进程无法加载
            # 系统 DLL，CreateProcess 抛 WinError 5（拒绝访问）
            safe_env = {
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONNOUSERSITE": "1",
            }
            # 复制系统运行必需的环境变量（不泄露业务配置如 TF_DB__URL）
            for _k in (
                "SystemRoot",
                "SystemDrive",
                "PATH",
                "TEMP",
                "TMP",
                "PATHEXT",
                "WINDIR",
                "COMSPEC",
            ):
                _v = os.environ.get(_k)
                if _v:
                    safe_env[_k] = _v

            # Windows: CREATE_NO_WINDOW 隐藏控制台窗口（不弹窗）
            # 注意: 不用 CREATE_BREAKAWAY_FROM_JOB — 当父进程不在 Job Object 中时
            # 该标志会触发 WinError 5（拒绝访问），Python 3.14 上已验证
            creationflags = 0
            if platform.system() == "Windows":
                creationflags = subprocess.CREATE_NO_WINDOW

            # Linux/macOS: preexec_fn 设置 rlimit（内存/CPU/进程数）
            preexec_fn = None
            if has_rlimit_support():
                preexec_fn = get_linux_preexec_fn(
                    memory_mb=256,
                    cpu_seconds=timeout + 5,  # CPU 时间略大于墙钟超时
                    nproc=64,
                )

            proc = subprocess.Popen(
                [sys.executable, "-S", "-u", tmp_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=safe_env,
                cwd=tempfile.gettempdir(),
                creationflags=creationflags,
                preexec_fn=preexec_fn if preexec_fn else None,  # noqa: PLW1509 - 沙箱设计为主线程调用，非线程池场景
            )

            # Windows Job Object 资源限制
            _apply_resource_limits_windows(proc)

            try:
                stdout_val, stderr_val = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                with contextlib.suppress(Exception):
                    proc.communicate()
                raise CodeExecutionTimeout(f"Code execution timed out after {timeout}s") from None

            stdout_val = stdout_val[:max_output]
            stderr_val = stderr_val[:max_output]

            if proc.returncode != 0:
                # 子进程执行失败 — 返回 stderr 作为错误
                err_msg = stderr_val.strip() or f"Process exited with code {proc.returncode}"
                raise RuntimeError(err_msg)

            # 从 stdout 提取 __TF_RESULT__ 标记后的 JSON 结果
            return self._extract_result(stdout_val)
        finally:
            if tmp_path:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)

    @staticmethod
    def _extract_result(stdout: str) -> Any:
        """从子进程 stdout 中提取 __TF_RESULT__ 标记后的 JSON 结果

        子进程 epilogue 会 print('__TF_RESULT__' + json.dumps(result))。
        用户代码可能也 print 内容到 stdout，故用 rfind 取最后一个标记。
        """
        marker = "__TF_RESULT__"
        idx = stdout.rfind(marker)
        if idx == -1:
            # 没有结果标记（用户代码可能未设置 result 或定义 main）
            return None
        json_str = stdout[idx + len(marker) :].strip()
        # 取第一行（防止后续输出干扰）
        if "\n" in json_str:
            json_str = json_str.split("\n", 1)[0]
        try:
            return json.loads(json_str)
        except (json.JSONDecodeError, ValueError):
            return None
