
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""DepartmentManager — Agent 部门看板引擎

职责: Agent 与部门的分配、排序、启用/停用
5部门: marketing / finance / service / research / ops
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog

from src.exceptions import AgentError
from src.infra.database.connection import get_connection_manager

logger = structlog.get_logger(__name__)

DEPARTMENTS = {
    "marketing": {"name_cn": "营销部", "emoji": "🎪", "color": "#ff5a32"},
    "finance": {"name_cn": "财务部", "emoji": "💰", "color": "#ffd700"},
    "service": {"name_cn": "客服部", "emoji": "🎧", "color": "#00f5ff"},
    "research": {"name_cn": "研究部", "emoji": "🔬", "color": "#b24bf3"},
    "ops": {"name_cn": "运营调度", "emoji": "⚙️", "color": "#39ff14"},
}

# 角色→部门的默认映射 (种子数据)
ROLE_DEPT_MAP = {
    "boss": "ops",
    "hitmaker": "marketing",
    "deal_hunter": "marketing",
    "researcher": "research",
    "support": "service",
    "companion": "service",
    "accountant": "finance",
    "butler": "ops",
    "compliance": "finance",
    "caster": "marketing",
    "analyst": "research",
}

# 专业Agent短名+图标映射 (人才池展示用)
AGENCY_DISPLAY_MAP: dict[str, dict[str, str]] = {
    # ── 营销师团 ──
    "agency-douyin": {"name_cn": "抖音运营", "emoji": "🎵"},
    "agency-xiaohongshu": {"name_cn": "小红书", "emoji": "📕"},
    "agency-wechat-oa": {"name_cn": "公众号", "emoji": "💬"},
    "agency-bilibili": {"name_cn": "B站", "emoji": "📺"},
    "agency-zhihu": {"name_cn": "知乎", "emoji": "💡"},
    "agency-weibo": {"name_cn": "微博", "emoji": "🔥"},
    "agency-kuaishou": {"name_cn": "快手", "emoji": "🎬"},
    "agency-seo": {"name_cn": "SEO优化", "emoji": "🔍"},
    "agency-baidu-seo": {"name_cn": "百度SEO", "emoji": "🎯"},
    "agency-growth": {"name_cn": "增长黑客", "emoji": "🚀"},
    "agency-content-strategy": {"name_cn": "内容策略", "emoji": "✍️"},
    "agency-livestream": {"name_cn": "直播电商", "emoji": "🎙️"},
    "agency-cross-border": {"name_cn": "跨境电商", "emoji": "🌏"},
    "agency-domestic-ecom": {"name_cn": "国内电商", "emoji": "🛒"},
    "agency-private-domain": {"name_cn": "私域运营", "emoji": "🏠"},
    # ── 财务师团 ──
    "agency-financial-analyst": {"name_cn": "财务分析", "emoji": "📊"},
    "agency-bookkeeper": {"name_cn": "记账月结", "emoji": "📒"},
    "agency-tax-strategist": {"name_cn": "税务策略", "emoji": "🏛️"},
    # ── 其他师团 ──
    "agency-supply-chain": {"name_cn": "供应链", "emoji": "🚢"},
    "agency-orchestrator": {"name_cn": "Agent编排", "emoji": "🔗"},
    "agency-studio-ops": {"name_cn": "工作室运营", "emoji": "⚙️"},
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _gen_id() -> str:
    return uuid.uuid4().hex[:16]


class DepartmentManager:
    """部门看板管理器 — 无状态，每次调用通过 conn 操作"""

    def list_departments(self) -> list[dict]:
        """列出所有部门及其 Agent 成员（含停用状态）"""
        cm = get_connection_manager()
        with cm.get_conn() as conn:
            result = []
            for dept_id, meta in DEPARTMENTS.items():
                rows = conn.execute(
                    "SELECT id, agent_id, agent_type, sort_order, pipe_pos, enabled "
                    "FROM agent_departments WHERE department = ? ORDER BY sort_order",
                    (dept_id,),
                ).fetchall()
                members = []
                for r in rows:
                    members.append(
                        {
                            "id": r["id"],
                            "agent_id": r["agent_id"],
                            "agent_type": r["agent_type"],
                            "sort_order": r["sort_order"],
                            "pipe_pos": r["pipe_pos"],
                            "enabled": bool(r["enabled"]),
                        }
                    )
                result.append(
                    {
                        "department": dept_id,
                        "name_cn": meta["name_cn"],
                        "emoji": meta["emoji"],
                        "color": meta["color"],
                        "members": members,
                        "member_count": len(members),
                    }
                )
            conn.rollback()  # 结束只读隐式事务，释放锁
            return result

    def assign_agent(
        self,
        agent_id: str,
        department: str,
        agent_type: str = "role",
        sort_order: int = 0,
    ) -> dict:
        """分配 Agent 到部门"""
        if department not in DEPARTMENTS:
            raise AgentError(f"未知部门: {department}")
        cm = get_connection_manager()
        with cm.get_conn() as conn:
            rid = _gen_id()
            now = _now()
            conn.execute(
                "INSERT OR REPLACE INTO agent_departments (id, agent_id, agent_type, department, sort_order, enabled, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                (rid, agent_id, agent_type, department, sort_order, now, now),
            )
            conn.commit()
            return {"id": rid, "agent_id": agent_id, "department": department}

    def remove_agent(self, agent_id: str, department: str) -> bool:
        """从部门移除 Agent"""
        cm = get_connection_manager()
        with cm.get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                "DELETE FROM agent_departments WHERE agent_id = ? AND department = ?",
                (agent_id, department),
            )
            conn.commit()
            return cur.rowcount > 0

    def reorder(self, department: str, agent_ids: list[str]) -> bool:
        """重排部门内 Agent 顺序"""
        cm = get_connection_manager()
        with cm.get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for idx, aid in enumerate(agent_ids):
                conn.execute(
                    "UPDATE agent_departments SET sort_order = ?, updated_at = ? WHERE agent_id = ? AND department = ?",
                    (idx, _now(), aid, department),
                )
            conn.commit()
            return True

    def toggle_agent(self, agent_id: str, department: str) -> dict:
        """启用/停用部门内的 Agent"""
        cm = get_connection_manager()
        with cm.get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT enabled FROM agent_departments WHERE agent_id = ? AND department = ?",
                (agent_id, department),
            ).fetchone()
            if not row:
                conn.rollback()
                raise AgentError(f"Agent {agent_id} 不在部门 {department} 中")
            new_val = 0 if row["enabled"] else 1
            conn.execute(
                "UPDATE agent_departments SET enabled = ?, updated_at = ? WHERE agent_id = ? AND department = ?",
                (new_val, _now(), agent_id, department),
            )
            conn.commit()
            return {"agent_id": agent_id, "department": department, "enabled": bool(new_val)}

    def get_talent_pool(self) -> list[dict]:
        """获取未分配部门的 Agent (人才池) — 覆盖 role + agency"""
        cm = get_connection_manager()
        with cm.get_conn() as conn:
            # 已分配的agent_id（无论启用与否）
            assigned = conn.execute("SELECT DISTINCT agent_id FROM agent_departments").fetchall()
            assigned_ids = {r["agent_id"] for r in assigned}

            pool = []

            # 1) 角色Agent — 来自ROLE_DEFINITIONS
            from src.engine.agent._defs import ROLE_DEFINITIONS

            for role, defn in ROLE_DEFINITIONS.items():
                if role.value not in assigned_ids:
                    pool.append(
                        {
                            "agent_id": role.value,
                            "agent_type": "role",
                            "name_cn": defn.name_cn,
                            "emoji": defn.emoji,
                        }
                    )

            # 2) 专业Agent — 来自AgentRegistry
            try:
                from src.engine.agent.specialist_base import get_agent_registry

                registry = get_agent_registry()
                for name, agent in registry._agents.items():
                    if name not in assigned_ids:
                        display = AGENCY_DISPLAY_MAP.get(name, {})
                        pool.append(
                            {
                                "agent_id": name,
                                "agent_type": "agency",
                                "name_cn": display.get("name_cn", name.replace("agency-", "")),
                                "emoji": display.get("emoji", "🤖"),
                                "category": getattr(agent, "category", "general"),
                            }
                        )
            except Exception as e:
                logger.warning("agency_pool_list_failed", error=str(e), exc_info=True)

            return pool

    def init_seed(self) -> dict:
        """初始化种子数据 — 将11角色分配到默认部门"""
        cm = get_connection_manager()
        with cm.get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            count = conn.execute("SELECT COUNT(*) as c FROM agent_departments").fetchone()["c"]
            if count > 0:
                return {"seeded": False, "reason": f"已有 {count} 条分配记录"}
            now = _now()
            for idx, (role, dept) in enumerate(ROLE_DEPT_MAP.items()):
                conn.execute(
                    "INSERT OR IGNORE INTO agent_departments (id, agent_id, agent_type, department, sort_order, enabled, created_at, updated_at) "
                    "VALUES (?, ?, 'role', ?, ?, 1, ?, ?)",
                    (_gen_id(), role, dept, idx, now, now),
                )
            conn.commit()
            return {"seeded": True, "count": len(ROLE_DEPT_MAP)}


# ── 单例 ──
_instance: DepartmentManager | None = None


def get_department_manager() -> DepartmentManager:
    global _instance
    if _instance is None:
        _instance = DepartmentManager()
    return _instance
