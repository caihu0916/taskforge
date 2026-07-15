
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""OutputGuardrail — 结构化输出校验 + 自动重试 (Instructor / LangChain 对标

设计:
  - 支持 JSON Schema 校验
  - 失败时构造 "上一轮输出 + 错误信息注入下一次 Prompt
  - 支持 Pydantic 模型校验 (可选依赖)

典型用例:
  - Agent 要求输出 JSON ({"risk_score": 0.72, "category": "high")
  - Agent 要求输出表格形式: [{"item": "A", "qty": 3}]
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_MAX_RETRY = 3

# ---------- JSON 提取器: 从 ```json...``` 或首个有效 JSON

_JSON_PATTERN = re.compile(r"```(?:json|JSON)?\s*([\s\S]+?)\s*```", re.IGNORECASE)


def extract_json(text: str) -> Any:
    """从 LLM 输出中提取 JSON。

    策略:
      1. 先尝试 ```json ... ```
      2. 再尝试 ``` ... ``` (无 json 标签)
      3. 再尝试整段文本为 JSON
      4. 最后尝试提取第一个 { 到最后一个 } 的范围
    """
    if not text:
        return None
    # 1) ```json ... ```
    m = _JSON_PATTERN.search(text)
    if m:
        candidate = m.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    # 2) 无 ``` 标签
    # 2) 整个文本为 JSON
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    # 3) 找最外层 { ... } / [ ... ]
    brace_start = text.find("{")
    bracket_start = text.find("[")
    start_candidates: list[int] = []
    if brace_start >= 0:
        start_candidates.append(brace_start)
    if bracket_start >= 0:
        start_candidates.append(bracket_start)
    if start_candidates:
        start_idx = min(start_candidates)
        # 找到匹配的结尾
        open_ch = text[start_idx]
        close_ch = "}" if open_ch == "{" else "]"
        depth = 0
        end_idx = -1
        in_str = False
        str_ch = ""
        i = start_idx
        while i < len(text):
            ch = text[i]
            if in_str:
                if ch == str_ch and text[i - 1] != "\\":
                    in_str = False
            elif ch in ('"', "'"):
                in_str = True
                str_ch = ch
            elif ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    end_idx = i
                    break
            i += 1
        if end_idx > start_idx:
            try:
                return json.loads(text[start_idx : end_idx + 1])
            except json.JSONDecodeError:
                pass
    return None


# ---------- JSON Schema 校验器


def validate_against_schema(data: Any, schema: dict[str, Any]) -> list[str]:
    """简化版 JSON Schema 校验 (不依赖 jsonschema 库)。

    支持: type, properties, required, items, enum, minLength, maxLength, minimum, maximum
    返回错误列表 (空列表 = 通过)。
    """
    errors: list[str] = []
    if not schema:
        return errors

    def check(value: Any, sch: dict[str, Any], path: str) -> None:
        expected_type = sch.get("type")
        # type 检查
        if expected_type:
            type_ok = _check_type(value, expected_type)
            if not type_ok:
                errors.append(f"{path or 'root'}: expected type {expected_type}, got {type(value).__name__}")
                return
        # enum 检查
        if "enum" in sch and value not in sch["enum"]:
            errors.append(f"{path or 'root'}: value {value!r} not in enum {sch['enum']}")
            return
        # object / properties
        if isinstance(value, dict):
            required = sch.get("required", [])
            for key in required:
                if key not in value:
                    errors.append(f"{path or 'root'}: missing required field '{key}'")
            properties = sch.get("properties", {})
            for key, sub_schema in properties.items():
                if key in value:
                    check(value[key], sub_schema, f"{path}.{key}" if path else key)
        # array / items
        elif isinstance(value, list) and "items" in sch:
            for i, item in enumerate(value):
                check(item, sch["items"], f"{path}[{i}]")
        # string length
        elif isinstance(value, str):
            if "minLength" in sch and len(value) < sch["minLength"]:
                errors.append(f"{path or 'root'}: string length {len(value)} < minLength {sch['minLength']}")
            if "maxLength" in sch and len(value) > sch["maxLength"]:
                errors.append(f"{path or 'root'}: string length {len(value)} > maxLength {sch['maxLength']}")
        # number range
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in sch and value < sch["minimum"]:
                errors.append(f"{path or 'root'}: value {value} < minimum {sch['minimum']}")
            if "maximum" in sch and value > sch["maximum"]:
                errors.append(f"{path or 'root'}: value {value} > maximum {sch['maximum']}")

    check(data, schema, "")
    return errors


def _check_type(value: Any, expected_type: str | list[str]) -> bool:
    if isinstance(expected_type, list):
        return any(_check_type(value, t) for t in expected_type)
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "null":
        return value is None
    return True


# ---------- 错误 Prompt 构造


def build_retry_prompt(
    original_prompt: str,
    previous_output: str,
    errors: list[str],
    schema: dict[str, Any] | None = None,
) -> str:
    """基于 "前一轮输出 + 错误信息" 的重试 Prompt 构造器。"""
    error_block = "\n".join(f"  - {e}" for e in errors) if errors else "  (无)"
    schema_block = ""
    if schema:
        try:
            schema_block = json.dumps(schema, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.debug("exception_handled", error=str(exc))
            schema_block = str(schema)
    parts = [
        "【输出格式校验失败】",
        "请严格按照下列要求重新输出。",
        "",
        "您上一轮的输出是:",
        previous_output[:500] if previous_output else "(空)",
        "",
        "检测到的错误:",
        error_block,
        "",
    ]
    if schema_block:
        parts += [
            "必须严格符合 JSON Schema:",
            "```json",
            schema_block,
            "```",
            "",
        ]
    parts += [
        "要求:",
        "1. 只输出 JSON, 不要额外说明",
        "2. 用 ```json ... ``` 包裹 JSON",
        "3. 字段必须齐全, 类型必须正确",
        "",
        "原始任务提示:",
        original_prompt[:200] if original_prompt else "(省略)",
    ]
    return "\n".join(parts)


# ---------- SchemaSpec — 结构化输出规范描述器 ----------

from dataclasses import dataclass, field


@dataclass
class SchemaSpec:
    """描述期望输出的 JSON Schema / Pydantic 模型。

    用法::

        spec = SchemaSpec(
            name="RiskAssessment",
            json_schema={
                "type": "object",
                "required": ["risk_score", "category"],
                "properties": {
                    "risk_score": {"type": "number", "minimum": 0, "maximum": 1},
                    "category": {"type": "string", "enum": ["low", "medium", "high"]},
                },
            },
            description="风险评估结果",
        )
        validator = OutputValidator(spec)
        result = validator.validate({"risk_score": 0.72, "category": "high"})
        assert result.is_valid
    """

    name: str = ""
    json_schema: dict[str, Any] | None = None
    pydantic_model: Any = None
    description: str = ""
    required_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "schema": self.json_schema,
            "description": self.description,
        }


# ---------- OutputValidator — 基于 SchemaSpec 的校验器 ----------


class OutputValidator:
    """基于 SchemaSpec 的输出校验器。

    支持:
      - JSON Schema 校验 (内置简化实现)
      - Pydantic 模型校验 (如 Pydantic 可用)
      - 字段级自定义校验规则
    """

    def __init__(self, spec: SchemaSpec | None = None) -> None:
        self.spec = spec
        self._call_count: int = 0

    def validate(self, data: Any) -> ValidationResult:
        """校验数据是否符合 SchemaSpec。

        Returns ValidationResult with is_valid=True if passes.
        """
        self._call_count += 1
        errors: list[str] = []

        if self.spec is None:
            # 无 spec 时跳过校验
            return ValidationResult(valid=True, data=data, errors=[], attempt=0)

        # 1) Pydantic 模型校验
        if self.spec.pydantic_model is not None:
            errors = OutputGuardrail._validate_with_pydantic(data, self.spec.pydantic_model)
            if errors:
                return ValidationResult(valid=False, data=data, errors=errors, attempt=0)

        # 2) JSON Schema 校验
        if self.spec.json_schema is not None:
            errors = validate_against_schema(data, self.spec.json_schema)
            if errors:
                return ValidationResult(valid=False, data=data, errors=errors, attempt=0)

        return ValidationResult(valid=True, data=data, errors=[], attempt=0)

    @property
    def call_count(self) -> int:
        return self._call_count


# ---------- ErrorRewriter — 失败时生成修复 Prompt ----------


class ErrorRewriter:
    """校验失败时生成带错误提示的二次 Prompt。

    用法::

        rewriter = ErrorRewriter()
        retry_prompt = rewriter.rewrite(
            original_prompt="分析发票风险",
            previous_output='{"risk_score": 0.8}',
            errors=["missing 'category' field"],
            schema={"type": "object", "required": ["category"]},
        )
    """

    def rewrite(
        self,
        original_prompt: str,
        previous_output: str,
        errors: list[str],
        schema: dict[str, Any] | None = None,
    ) -> str:
        """生成重试 Prompt。"""
        return build_retry_prompt(
            original_prompt=original_prompt,
            previous_output=previous_output,
            errors=errors,
            schema=schema,
        )


# ---------- OutputGuardrail 引擎


class OutputGuardrail:
    """结构化输出校验 + 自动重试。

    典型用法::

        guardrail = OutputGuardrail()
        result = guardrail.validate(
            "你是财务审核员, 请输出风险评估 JSON",
            llm_output,
            schema={"type": "object", "properties": {"risk_score": {"type": "number"}}},
            llm_provider=my_llm,
        )
        if result.valid:
            use(result.data)
        else:
            report(result.errors)
    """

    def __init__(self, max_retry: int = _MAX_RETRY) -> None:
        self.max_retry = max_retry
        self._call_count = 0

    # ── 核心 API ──

    def validate(
        self,
        task_prompt: str,
        raw_output: str,
        schema: dict[str, Any] | None = None,
        pydantic_model: Any = None,
        llm_provider: Any = None,
    ) -> ValidationResult:
        """校验 LLM 输出是否符合要求。

        参数:
          task_prompt: 原始任务提示 (用于重试时注入)
          raw_output: LLM 原始输出 (字符串)
          schema: JSON Schema (可选)
          pydantic_model: Pydantic 模型类 (可选)
          llm_provider: 支持 .call(prompt) -> str 的 LLM 提供者 (可选, 用于重试)
        """
        self._call_count += 1
        current_output = raw_output
        attempt = 0
        last_errors: list[str] = []
        last_data: Any = None

        while attempt <= self.max_retry:
            # 1) 提取 JSON
            data = extract_json(current_output)
            if data is None:
                last_errors = ["无法从输出中解析出 JSON"]
            else:
                last_data = data
                # 2) Schema 校验
                errs: list[str] = []
                if pydantic_model is not None:
                    errs = self._validate_with_pydantic(data, pydantic_model)
                elif schema:
                    errs = validate_against_schema(data, schema)
                if not errs:
                    # 3) 成功!
                    return ValidationResult(
                        valid=True,
                        data=data,
                        errors=[],
                        attempt=attempt,
                        raw=current_output,
                    )
                last_errors = errs

            # 失败 → 如需重试, 但首次解析失败也不重写 last_errors
            if attempt >= self.max_retry or llm_provider is None:
                break

            # 构造重试 Prompt
            retry_prompt = build_retry_prompt(task_prompt, current_output, last_errors, schema)
            try:
                current_output = llm_provider(retry_prompt)
                attempt += 1
                logger.info(
                    "output_guardrail_retry",
                    attempt=attempt,
                    error_count=len(last_errors),
                )
            except Exception as e:
                logger.warning("output_guardrail_llm_failed", error=str(e))
                break

        # 所有重试都失败
        return ValidationResult(
            valid=False,
            data=last_data,
            errors=last_errors,
            attempt=attempt,
            raw=current_output,
        )

    # ── Pydantic 校验 (可选依赖)

    @staticmethod
    def _validate_with_pydantic(data: Any, model: Any) -> list[str]:
        try:
            import pydantic  # type: ignore

            try:
                model.model_validate(data)
                return []
            except pydantic.ValidationError as exc:  # type: ignore
                return [f"{e['loc']}: {e['msg']}" for e in exc.errors()]  # type: ignore
        except ImportError:
            # 无 Pydantic: 降级为仅检查必填字段是否存在 (若 model 有字段名)
            try:
                field_names = getattr(model, "model_fields", {})
                required = [name for name, info in field_names.items() if getattr(info, "is_required", True)]
                missing = [f for f in required if f not in (data or {})]
                if missing:
                    return [f"缺少字段: {', '.join(missing)}"]
            except Exception as e:
                logger.debug("output_guardrail_schema_validate_failed", error=str(e))
            return []


# ---------- 结果对象

from dataclasses import dataclass, field


@dataclass
class ValidationResult:
    """输出校验结果。"""

    valid: bool = False
    data: Any = None
    errors: list[str] = field(default_factory=list)
    attempt: int = 0
    raw: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "data": self.data,
            "errors": self.errors,
            "attempt": self.attempt,
            "has_data": self.data is not None,
        }
