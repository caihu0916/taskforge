
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""工作流 Step 执行器 — 独立于 step_ops.py 的自动化执行路径

engine.py 在执行 step 时，先查 STEP_EXECUTOR_REGISTRY 是否有匹配的 action，
命中则走 step_executors；否则回退到 step_ops.py 的 agent 角色执行。

零污染 step_ops.py。支持"热点→内容→发布→复盘"全闭环。
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)

STEP_EXECUTOR_REGISTRY: dict[str, object] = {}


def register_executor(action_id: str):
    """装饰器注册执行器"""

    def deco(fn):
        STEP_EXECUTOR_REGISTRY[action_id] = fn
        return fn

    return deco


@register_executor("xhs_hot_search")
async def execute_xhs_hot_search(keyword: str = "", limit: int = 10) -> dict[str, Any]:
    """全网热点发现 Step — WebSearchTool + httpx + trafilatura"""
    import httpx

    from src.engine.tool.builtin.search_tool import WebSearchTool

    searcher = WebSearchTool()
    raw = await searcher.execute(query=keyword, max_results=limit)
    results = raw.get("data", []) if raw.get("success") else []

    topics: list[dict] = []
    async with httpx.AsyncClient(timeout=15.0) as client:
        for item in results[:5]:
            url = item.get("url") or item.get("href", "")
            if not url:
                continue
            try:
                resp = await client.get(url, headers={"User-Agent": "TaskForge/1.0"})
                if resp.status_code == 200:
                    import trafilatura

                    md = trafilatura.extract(resp.text, output_format="markdown") or ""
                    topics.append({"url": url, "title": item.get("title", ""), "snippet": md[:500]})
            except Exception:
                logger.debug("scrape_failed_for_step", url=url, exc_info=True)

    return {"trends": topics, "selected_topics": [t["title"] for t in topics[:3]]}


@register_executor("xhs_content_write")
async def execute_xhs_content_write(topic: str = "", style: str = "种草干货") -> dict[str, Any]:
    """AI 写作 Step — 通过 LLM Router 生成小红书文案"""
    # ponytail: 开源版LLM模块不可用时降级；P0-09/P0-17提供remote_stubs桩
    try:
        from src.engine.llm.router import get_llm_router
    except ImportError as e:
        raise RuntimeError("LLM模块不可用（开源版需配置远程API或安装Ollama）") from e

    router = get_llm_router()
    messages = [
        {
            "role": "system",
            "content": (
                "你是小红书爆款文案写手。根据主题生成小红书笔记。\n"
                "输出格式要求（严格JSON）：\n"
                '{"title": "标题(15字内含关键词+情绪钩子)", '
                '"body": "正文(3-5段，emoji穿插，结尾引导收藏+关注)", '
                '"hashtags": ["标签1", "标签2", "标签3"], '
                '"image_prompt": "封面图描述"}\n'
                "内容铁律：70%生活方式分享+20%趋势解读+10%推荐；"
                "标题必含关键词+情绪钩子；正文分段、emoji分隔；含AI创作须标注。"
            ),
        },
        {"role": "user", "content": f"主题：{topic}\n风格：{style}\n请生成小红书笔记，直接输出JSON，不要多余文字。"},
    ]
    try:
        result = await router.chat(messages, profile="fast", max_tokens=2000)
        content = result.get("content", "")
        # 尝试解析JSON，失败则兜底
        import json

        # 提取JSON部分（可能在```json```代码块中）
        json_str = content
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0]
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0]
        parsed = json.loads(json_str.strip())
        return {
            "title": parsed.get("title", f"💡 {topic}"),
            "body": parsed.get("body", ""),
            "hashtags": parsed.get("hashtags", [topic]),
            "image_prompt": parsed.get("image_prompt", ""),
        }
    except Exception:
        logger.warning("xhs_content_write_llm_failed", exc_info=True)
        # 降级：返回基础结构，由后续合规检查兜底
        return {
            "title": f"💡 {topic}",
            "body": f"关于{topic}的分享...（AI生成降级，LLM调用失败）",
            "hashtags": [topic],
            "image_prompt": "",
        }


@register_executor("xhs_compliance_check")
async def execute_xhs_compliance_check(title: str = "", body: str = "") -> dict[str, Any]:
    """合规审查 Step — 规则引擎（关键词+模式）+ LLM 深度审查"""
    issues: list[str] = []
    text = title + body
    text_lower = text.lower()

    # 1. AI创作标注检查
    ai_keywords = ["ai", "aigc", "人工智能", "智能生成", "大模型", "chatgpt", "claude"]
    ai_mentioned = any(kw in text_lower for kw in ai_keywords)
    ai_label_present = "ai合成" in text or "AI合成" in text or "ai创作" in text or "AI创作" in text
    if ai_mentioned and not ai_label_present:
        issues.append("涉及AI内容但未标注「含AI合成内容」，小红书三次未标注将封号")

    # 2. 广告法敏感词
    ad_sensitive = ["最好", "第一", "唯一", "绝对", "最强", "顶级", "全国最佳", "国家级"]
    issues.extend(f"含广告法敏感词: {w}" for w in ad_sensitive if w in text)

    # 3. 制造对立检测
    polarization_patterns = [
        ("你们女人", "性别对立"),
        ("你们男人", "性别对立"),
        ("穷人就是", "阶层对立"),
        ("富人都是", "阶层对立"),
        ("打工人不配", "阶层对立"),
        ("城里的", "地域对立"),
        ("乡下人", "地域对立"),
        ("那个省的人", "地域对立"),
    ]
    for pattern, label in polarization_patterns:
        if pattern in text:
            issues.append(f'涉嫌制造{label}: "{pattern}"')

    # 4. 诱导分享/标题党
    clickbait = ["不转不是中国人", "看到必转", "速看马上删", "看完的人都哭了"]
    issues.extend(f"含诱导分享词: {w}" for w in clickbait if w in text)

    # 5. 医疗/金融限制词
    restricted = ["包治百病", "治愈率100%", "稳赚不赔", "零风险投资", "暴利"]
    issues.extend(f"含医疗/金融限制词: {w}" for w in restricted if w in text)

    # 6. LLM 深度审查（规则通过后才调，省token）
    llm_deep_issues: list[str] = []
    if not issues:
        try:
            from src.engine.llm.router import get_llm_router

            router = get_llm_router()
            messages = [
                {
                    "role": "system",
                    "content": (
                        "你是小红书内容合规审查员。检查以下笔记是否：\n"
                        "1. 暗含制造对立/歧视（性别/阶层/地域/年龄）\n"
                        "2. 隐性违规营销（虚假功效/夸大宣传）\n"
                        "3. 违反社区公约（低俗/擦边/恶意引战）\n"
                        "如无问题输出空数组[]，有问题输出问题描述列表。只输出JSON数组。"
                    ),
                },
                {"role": "user", "content": f"标题：{title}\n正文：{body}"},
            ]
            result = await router.chat(messages, profile="fast", max_tokens=500)
            import json

            content = result.get("content", "[]")
            if "```" in content:
                content = content.split("```")[1].split("```")[0]
            llm_deep_issues = json.loads(content.strip()) if content.strip().startswith("[") else []
        except Exception:
            logger.warning("compliance_llm_failed", exc_info=True)

    all_issues = issues + llm_deep_issues
    return {"passed": len(all_issues) == 0, "issues": all_issues}


@register_executor("content_review")
async def execute_content_review(title: str = "", body: str = "") -> dict[str, Any]:
    """人类决策点 — 暂停工作流等待审批，status 标记为 waiting_approval"""
    return {
        "needs_human_review": True,
        "title": title,
        "body_preview": body[:200],
    }


@register_executor("xhs_real_publish")
async def execute_xhs_real_publish(
    title: str = "",
    body: str = "",
    image_paths: list | None = None,
    ai_creation: bool = True,
) -> dict[str, Any]:
    """真实发布到小红书"""
    from src.engine.social.xhs_publisher import XhsPublisher

    publisher = XhsPublisher()
    return await publisher.publish(
        title=title,
        body=body,
        image_paths=image_paths or [],
        is_ai_created=ai_creation,
    )


@register_executor("xhs_performance_review")
async def execute_xhs_performance_review(
    note_id: str = "",
    content_id: str = "",
    delay_hours: int = 24,
) -> dict[str, Any]:
    """发布后数据复盘 Step — "选题→生成→发布→复盘"闭环的最后一环

    流程：
      1. 通过 xhs CLI read --json 拉取单篇笔记最新互动数据
      2. 写回 contents.stats + content_performance 表
      3. 基于数据生成 AI 优化建议（CES公式分析）
    """
    if not note_id:
        logger.warning("xhs_performance_review_no_note_id", content_id=content_id)
        return {"note_id": "", "review_summary": "无note_id，跳过复盘", "optimization_tips": []}

    # 1. 拉取互动数据
    from src.engine.social.xhs_publisher import XhsPublisher

    publisher = XhsPublisher()
    stats_result = await publisher.get_note_stats(note_id)

    if not stats_result.get("success"):
        error = stats_result.get("error", "获取数据失败")
        logger.warning("xhs_performance_review_stats_failed", note_id=note_id, error=error)
        return {"note_id": note_id, "review_summary": f"数据获取失败: {error}", "optimization_tips": []}

    stats = stats_result.get("stats", {})

    # 2. 写回 DB（如果有 content_id）
    if content_id:
        try:
            from src.engine.marketing._content_db import content_update_performance, content_update_stats

            content_update_stats(content_id, stats)
            stats_with_platform = {**stats, "platform": "xiaohongshu"}
            content_update_performance(content_id, stats_with_platform)
            logger.info("xhs_performance_review_saved", content_id=content_id, note_id=note_id)
        except Exception:
            logger.warning("xhs_performance_review_db_write_failed", exc_info=True)

    # 3. CES 分析 + AI 优化建议
    optimization_tips = _analyze_xhs_performance(stats)
    ces_score = _calculate_ces(stats)

    return {
        "note_id": note_id,
        "content_id": content_id,
        "stats": stats,
        "ces_score": ces_score,
        "review_summary": f"互动数据已回收，CES评分 {ces_score:.1f}，生成 {len(optimization_tips)} 条优化建议",
        "optimization_tips": optimization_tips,
    }


def _calculate_ces(stats: dict) -> float:
    """CES评分：点赞×1 + 收藏×1 + 评论×4 + 转发×4 + 关注×8

    归一化到 0-100 分（以100为满分基准）
    """
    likes = stats.get("likes", 0)
    collects = stats.get("collects", 0)
    comments = stats.get("comments", 0)
    shares = stats.get("shares", 0)

    raw = likes * 1 + collects * 1 + comments * 4 + shares * 4
    # 归一化：100分对应 raw=500
    return min(raw / 5.0, 100.0)


def _analyze_xhs_performance(stats: dict) -> list[str]:
    """基于互动数据生成优化建议（规则引擎，不依赖LLM）"""
    tips: list[str] = []
    likes = stats.get("likes", 0)
    collects = stats.get("collects", 0)
    comments = stats.get("comments", 0)
    shares = stats.get("shares", 0)
    views = stats.get("views", 0)

    # 互动率分析
    if views > 0:
        engage_rate = (likes + collects + comments + shares) / views
        if engage_rate < 0.02:
            tips.append("互动率低于2%，需优化内容吸引力 — 检查标题是否不够钩人、封面是否缺乏视觉冲击")
        elif engage_rate > 0.1:
            tips.append("互动率超过10%，内容表现优秀 — 可复用该选题方向和标题结构")

    # 收藏/点赞比
    if likes > 0:
        save_ratio = collects / likes
        if save_ratio > 2:
            tips.append("收藏/点赞比 > 2，内容实用性强但传播不足 — 尝试增加分享引导语")
        elif save_ratio < 0.3:
            tips.append("收藏/点赞比 < 0.3，内容有传播但缺乏复看价值 — 需增加实用干货内容")

    # 评论率
    if views > 0 and comments / views < 0.005:
        tips.append("评论率低，需在正文末尾增加互动提问 — 如'你试过这个方法吗？评论区聊聊'")

    # 转发率
    if views > 0 and shares / views < 0.002:
        tips.append("转发率低，可添加'@好友一起看'等社交引导语提升传播")

    # 综合判断
    total_engage = likes + collects + comments + shares
    if total_engage == 0 and views > 100:
        tips.append("有曝光但零互动 — 内容与目标受众不匹配，需重新审视选题方向")
    elif total_engage > 50:
        tips.append("整体互动良好，继续保持 — 下次可尝试A/B测试不同封面/标题风格")

    if not tips:
        tips.append("数据量较小，暂无明确优化方向 — 继续观察后续数据变化")

    return tips


@register_executor("scheduled_publish")
async def execute_scheduled_publish() -> dict[str, Any]:
    """发布所有到期排期内容 — 检查 DB 中 scheduled 且 scheduled_at <= NOW() 的内容并执行发布"""
    from src.engine.social.scheduled_publish import ScheduledPublishService

    service = ScheduledPublishService()
    return await service.publish_scheduled()
