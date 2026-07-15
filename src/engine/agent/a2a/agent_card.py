
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""A2A Agent Card 数据结构(P1-INF-003)

Agent Card 是 A2A Protocol 的标准元数据,描述 Agent 的能力。
用于 /api/v1/agents/{id}/card 端点返回。

规范来源: https://github.com/google-a2a/A2A

字段:
  - name: Agent 唯一标识(如 "sales-assistant")
  - description: 人类可读描述
  - skills: 技能列表(如 ["lead-qualification", "deal-tracking"])
  - tools: 工具列表(如 ["crm.query", "email.send"])
  - capabilities: 能力声明(如 ["text-generation", "function-calling"])
  - url(可选): Agent 服务端点
  - version(可选): Agent 版本
  - protocol(可选): 通信协议(默认 "a2a")

AGENT-015 安全策略:
  - to_dict(): 内部使用, 暴露全部字段
  - to_public_dict(): 对外暴露, 仅返回最小字段集 (name/description/skills/version/protocol)
    隐藏内部 tools/capabilities/url 等敏感信息, 减少攻击面
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# AGENT-015: 对外暴露的最小字段集 — 不含 tools/capabilities/url 等内部信息
_PUBLIC_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "description",
        "skills",
        "version",
        "protocol",
    }
)


@dataclass
class AgentCard:
    """A2A Agent Card — Agent 元数据与能力声明"""

    name: str
    description: str
    skills: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    # 可选字段
    url: str = ""
    version: str = "1.0.0"
    protocol: str = "a2a"

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典(用于 API 响应)"""
        return {
            "name": self.name,
            "description": self.description,
            "skills": list(self.skills),
            "tools": list(self.tools),
            "capabilities": list(self.capabilities),
            "url": self.url,
            "version": self.version,
            "protocol": self.protocol,
        }

    def to_public_dict(self) -> dict[str, Any]:
        """AGENT-015: 序列化为对外公开的最小字段集 — 字段最小化

        仅暴露: name, description, skills, version, protocol
        隐藏: tools, capabilities, url (内部信息, 减少攻击面)

        Returns:
            仅包含公开字段的字典
        """
        return {
            "name": self.name,
            "description": self.description,
            "skills": list(self.skills),
            "version": self.version,
            "protocol": self.protocol,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentCard:
        """从字典反序列化"""
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            skills=list(data.get("skills", [])),
            tools=list(data.get("tools", [])),
            capabilities=list(data.get("capabilities", [])),
            url=data.get("url", ""),
            version=data.get("version", "1.0.0"),
            protocol=data.get("protocol", "a2a"),
        )
