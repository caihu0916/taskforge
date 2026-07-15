
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""TaskForge 智能意图理解引擎 — 语义理解 + 实体提取 + 上下文感知

核心能力:
  1. 意图分类: 支持多意图识别（主意图 + 辅助意图）
  2. 实体提取: 自动识别时间、地点、人物、数值等实体
  3. 上下文理解: 结合对话历史理解指代和省略
  4. 置信度评估: 为每个意图提供置信度分数

设计原则:
  - 分层处理: 先规则快速过滤，再LLM精细分析
  - 可扩展: 支持自定义意图模板
  - 向后兼容: 不破坏现有关键词匹配机制
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger("taskforge.intent")


# ── 意图类型定义 ──
class IntentType:
    """意图类型常量"""

    # 通用意图
    UNKNOWN = "unknown"
    GREETING = "greeting"
    FAREWELL = "farewell"
    THANKS = "thanks"
    HELP = "help"

    # 信息查询
    WEATHER = "weather"
    SEARCH = "search"
    KNOWLEDGE = "knowledge"
    CALCULATE = "calculate"

    # 任务操作
    CREATE_TASK = "create_task"
    UPDATE_TASK = "update_task"
    DELETE_TASK = "delete_task"
    QUERY_TASK = "query_task"

    # 文档操作
    CREATE_DOC = "create_doc"
    READ_DOC = "read_doc"
    UPDATE_DOC = "update_doc"

    # 商业意图
    INQUIRY = "inquiry"
    PURCHASE = "purchase"
    COLLABORATION = "collaboration"
    CONSULTATION = "consultation"

    # 系统操作
    SETTING = "setting"
    DEBUG = "debug"
    STATUS = "status"


# ── 实体类型定义 ──
class EntityType:
    """实体类型常量"""

    CITY = "city"
    DATE = "date"
    TIME = "time"
    NUMBER = "number"
    MONEY = "money"
    PHONE = "phone"
    EMAIL = "email"
    WECHAT = "wechat"
    URL = "url"
    PERSON = "person"
    ORGANIZATION = "organization"
    PRODUCT = "product"
    LOCATION = "location"


# ── 数据结构 ──


@dataclass
class Entity:
    """提取的实体"""

    type: str  # EntityType 常量
    value: str
    normalized_value: str | None = None
    confidence: float = 1.0
    start_pos: int = -1
    end_pos: int = -1


@dataclass
class IntentResult:
    """意图识别结果"""

    intents: list[IntentMatch] = field(default_factory=list)
    entities: list[Entity] = field(default_factory=list)
    confidence: float = 0.0
    original_text: str = ""
    context_summary: str = ""


@dataclass
class IntentMatch:
    """单个意图匹配"""

    intent_type: str
    confidence: float
    trigger_words: list[str] = field(default_factory=list)


# ── 意图模板 ──

_INTENT_TEMPLATES = {
    # 天气查询
    IntentType.WEATHER: {
        "keywords": {"天气", "气温", "温度", "预报", "晴天", "下雨", "刮风", "雾霾"},
        "patterns": [
            r".*([市省])的?天气",
            r".*(今天|明天|后天|周末|下周).*天气",
            r".*气温.*(多少|度)",
            r".*(晴|雨|雪|风|云).*预报",
        ],
    },
    # 搜索查询
    IntentType.SEARCH: {
        "keywords": {"搜索", "查一下", "查找", "了解", "看看", "有什么"},
        "patterns": [],
    },
    # 知识查询
    IntentType.KNOWLEDGE: {
        "keywords": {"是什么", "为什么", "怎么样", "如何", "什么是", "原理", "解释"},
        "patterns": [
            r".*是什么\??",
            r".*为什么.*\??",
            r".*如何.*\??",
            r".*原理.*\??",
        ],
    },
    # 计算
    IntentType.CALCULATE: {
        "keywords": {"计算", "算一下", "等于", "加", "减", "乘", "除", "求和", "多少"},
        "patterns": [
            r".*(\d+)\s*[+−×÷*/]\s*(\d+)",
            r".*等于多少\??",
            r".*求和.*",
        ],
    },
    # 问候
    IntentType.GREETING: {
        "keywords": {"你好", "您好", "hi", "hello", "哈喽", "在吗", "有人吗"},
        "patterns": [],
    },
    # 告别
    IntentType.FAREWELL: {
        "keywords": {"再见", "拜拜", "走了", "下次见", "88"},
        "patterns": [],
    },
    # 感谢
    IntentType.THANKS: {
        "keywords": {"谢谢", "感谢", "辛苦了", "谢谢啦"},
        "patterns": [],
    },
    # 帮助
    IntentType.HELP: {
        "keywords": {"帮助", "帮忙", "求助", "怎么办", "怎么弄", "如何"},
        "patterns": [
            r".*怎么.*\??",
            r".*如何.*\??",
            r".*帮忙.*",
        ],
    },
}


# ── 实体提取模式 ──

_ENTITY_PATTERNS = {
    EntityType.CITY: [
        re.compile(
            r"(北京|上海|广州|深圳|重庆|天津|南京|杭州|成都|武汉|西安|苏州|郑州|长沙|沈阳|青岛|济南|哈尔滨|佛山|东莞|宁波|无锡|合肥|昆明|大连|厦门|福州|石家庄|贵阳|南宁|太原|南昌|长春|温州|常州|嘉兴|金华|绍兴|台州|惠州|中山|珠海|江门|佛山|东莞|南宁|柳州|桂林|海口|三亚|烟台|潍坊|淄博|临沂|济宁|东营|威海|泰安|德州|滨州|菏泽|枣庄|日照|莱芜|聊城|滨州|东营|威海|泰安|德州|滨州|菏泽|枣庄|日照|莱芜|聊城)",
            re.IGNORECASE,
        ),
    ],
    EntityType.DATE: [
        re.compile(r"(今天|明天|后天|昨天|前天|大前天|大后天)"),
        re.compile(r"(本周|下周|上周)(一|二|三|四|五|六|日)?"),
        re.compile(r"(周一|周二|周三|周四|周五|周六|周日)"),
        re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日?"),
        re.compile(r"(\d{1,2})月(\d{1,2})日?"),
        re.compile(r"(\d{1,2})号"),
        re.compile(r"(元旦|春节|元宵节|清明节|劳动节|端午节|中秋节|国庆节)"),
    ],
    EntityType.TIME: [
        re.compile(r"(\d{1,2}):(\d{2})(:\d{2})?"),
        re.compile(r"(\d{1,2})点(\d{2})?分?"),
        re.compile(r"(早上|上午|中午|下午|晚上|凌晨|深夜)(\d{1,2})点?(\d{2})?分?"),
    ],
    EntityType.NUMBER: [
        re.compile(r"(\d+(?:\.\d+)?)"),
    ],
    EntityType.MONEY: [
        re.compile(r"(\d+(?:\.\d+)?)\s*(元|块|万元|亿|美元|欧元|英镑|日元)"),
    ],
    EntityType.PHONE: [
        re.compile(r"1[3-9]\d{9}"),
    ],
    EntityType.EMAIL: [
        re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    ],
    EntityType.WECHAT: [
        re.compile(r"微信[：:]?\s*(\w{5,20})", re.IGNORECASE),
        re.compile(r"wechat[：:]?\s*(\w{5,20})", re.IGNORECASE),
        re.compile(r"wx[：:]?\s*(\w{5,20})", re.IGNORECASE),
    ],
    EntityType.URL: [
        re.compile(r"https?://[\w.-]+(?:/[\w./-]*)?"),
    ],
}


class IntentEngine:
    """智能意图理解引擎"""

    def __init__(self):
        self._intent_templates = _INTENT_TEMPLATES
        self._entity_patterns = _ENTITY_PATTERNS

    def parse(self, text: str, conversation_history: list[dict] | None = None) -> IntentResult:
        """解析用户消息，提取意图和实体

        Args:
            text: 用户输入文本
            conversation_history: 对话历史（用于上下文理解）

        Returns:
            IntentResult: 包含意图列表和实体列表
        """
        if not text or not text.strip():
            return IntentResult(original_text=text)

        text = text.strip()

        # 1. 提取实体
        entities = self._extract_entities(text)

        # 2. 识别意图
        intents = self._detect_intents(text, entities)

        # 3. 计算整体置信度
        confidence = self._calc_overall_confidence(intents)

        # 4. 生成上下文摘要
        context_summary = self._build_context_summary(text, conversation_history, entities)

        return IntentResult(
            intents=intents,
            entities=entities,
            confidence=confidence,
            original_text=text,
            context_summary=context_summary,
        )

    def _extract_entities(self, text: str) -> list[Entity]:
        """从文本中提取实体"""
        entities = []
        seen_spans = set()  # 避免重复提取

        for entity_type, patterns in self._entity_patterns.items():
            for pattern in patterns:
                for match in pattern.finditer(text):
                    start, end = match.span()
                    # 跳过已提取的区域
                    if any(start < e_end and end > e_start for e_start, e_end in seen_spans):
                        continue

                    value = match.group(0)
                    normalized = self._normalize_entity(entity_type, value)

                    entities.append(
                        Entity(
                            type=entity_type,
                            value=value,
                            normalized_value=normalized,
                            confidence=1.0,
                            start_pos=start,
                            end_pos=end,
                        )
                    )
                    seen_spans.add((start, end))

        # 按位置排序
        entities.sort(key=lambda e: e.start_pos)
        return entities

    def _normalize_entity(self, entity_type: str, value: str) -> str | None:
        """标准化实体值"""
        try:
            if entity_type == EntityType.DATE:
                return self._normalize_date(value)
            if entity_type == EntityType.TIME:
                return self._normalize_time(value)
            if entity_type == EntityType.MONEY:
                return self._normalize_money(value)
            if entity_type == EntityType.NUMBER:
                return str(float(value))
        except Exception:
            logger.debug("intent_entity_normalize_failed", entity_type=str(entity_type), value=str(value)[:80])
        return None

    def _normalize_date(self, value: str) -> str:
        """标准化日期"""
        # 简单实现，实际应用中可以使用 dateparser 库
        today_map = {"今天": "today", "明天": "tomorrow", "后天": "day_after_tomorrow"}
        return today_map.get(value, value)

    def _normalize_time(self, value: str) -> str:
        """标准化时间"""
        # 简单实现
        return value.replace("点", ":").replace("分", "")

    def _normalize_money(self, value: str) -> str:
        """标准化金额"""
        # 提取数字部分
        match = re.search(r"\d+(?:\.\d+)?", value)
        return match.group() if match else value

    def _detect_intents(self, text: str, entities: list[Entity]) -> list[IntentMatch]:
        """识别意图"""
        matches = []
        text_lower = text.lower()

        for intent_type, template in self._intent_templates.items():
            confidence = 0.0
            triggers = []

            # 关键词匹配
            for keyword in template["keywords"]:
                if keyword.lower() in text_lower:
                    confidence += 0.2
                    triggers.append(keyword)
                    if confidence >= 1.0:
                        break

            # 正则模式匹配
            for pattern in template["patterns"]:
                if re.search(pattern, text, re.IGNORECASE):
                    confidence += 0.3
                    triggers.append(f"pattern:{pattern}")
                    if confidence >= 1.0:
                        break

            # 实体增强
            relevant_entities = self._get_relevant_entities(intent_type, entities)
            if relevant_entities:
                confidence += 0.1 * len(relevant_entities)

            # 置信度归一化
            confidence = min(confidence, 1.0)

            if confidence >= 0.3:  # 最小置信度阈值
                matches.append(
                    IntentMatch(
                        intent_type=intent_type,
                        confidence=round(confidence, 2),
                        trigger_words=triggers,
                    )
                )

        # 按置信度排序
        matches.sort(key=lambda m: -m.confidence)

        # 如果没有匹配，检查是否是未知意图
        if not matches:
            matches.append(
                IntentMatch(
                    intent_type=IntentType.UNKNOWN,
                    confidence=1.0,
                    trigger_words=[],
                )
            )

        return matches

    def _get_relevant_entities(self, intent_type: str, entities: list[Entity]) -> list[Entity]:
        """获取与意图相关的实体"""
        relevant_types = {
            IntentType.WEATHER: {EntityType.CITY, EntityType.DATE, EntityType.TIME},
            IntentType.SEARCH: {EntityType.CITY, EntityType.DATE},
            IntentType.CALCULATE: {EntityType.NUMBER, EntityType.MONEY},
            IntentType.INQUIRY: {EntityType.PRODUCT, EntityType.MONEY, EntityType.PHONE, EntityType.WECHAT},
        }
        types = relevant_types.get(intent_type, set())
        return [e for e in entities if e.type in types]

    def _calc_overall_confidence(self, intents: list[IntentMatch]) -> float:
        """计算整体置信度"""
        if not intents:
            return 0.0
        # 取最高置信度作为整体置信度
        return max(i.confidence for i in intents)

    def _build_context_summary(self, text: str, history: list[dict] | None, entities: list[Entity]) -> str:
        """构建上下文摘要"""
        parts = []

        # 实体摘要
        if entities:
            entity_info = []
            for e in entities[:5]:  # 最多取5个
                entity_info.append(f"{e.type}: {e.value}")
            parts.append(f"实体: {', '.join(entity_info)}")

        # 历史上下文提示
        if history and len(history) > 0:
            recent_user_msgs = [m for m in history[-3:] if m.get("role") == "user"]
            if recent_user_msgs:
                parts.append(f"历史对话: {len(recent_user_msgs)} 轮")

        return "; ".join(parts)

    # ── LLM增强意图识别 ──

    async def enhance_with_llm(self, result: IntentResult) -> IntentResult:
        """使用LLM增强意图识别结果

        当置信度在中间范围时，使用LLM进行二次确认和更精细的分析。
        """
        if result.confidence >= 0.8 or result.confidence <= 0.2:
            # 置信度足够高或足够低，无需LLM增强
            return result

        try:
            from src.engine.llm.router import get_llm_router

            router = get_llm_router()
            if not router:
                return result

            # 构建prompt
            entities_str = "\n".join([f"- {e.type}: {e.value}" for e in result.entities])
            intents_str = "\n".join([f"- {i.intent_type}: {i.confidence}" for i in result.intents])

            prompt = f"""
分析以下用户消息，进行精细的意图识别和实体提取：

用户消息: {result.original_text}

已识别的意图（需要优化）:
{intents_str}

已提取的实体（需要验证）:
{entities_str}

请输出JSON格式，包含：
1. intents: 意图列表，每个包含 intent_type（字符串）和 confidence（0-1）
2. entities: 实体列表，每个包含 type（实体类型）和 value（实体值）
3. main_intent: 主意图类型
4. confidence: 整体置信度

只输出JSON，不要其他内容。
"""

            llm_result = await router.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=500,
            )

            if llm_result and llm_result.get("content"):
                import json

                try:
                    data = json.loads(llm_result["content"])
                    # 合并LLM结果
                    if data.get("intents"):
                        result.intents = [
                            IntentMatch(
                                intent_type=i["intent_type"],
                                confidence=i["confidence"],
                            )
                            for i in data["intents"]
                        ]
                    if data.get("entities"):
                        result.entities.extend([Entity(type=e["type"], value=e["value"]) for e in data["entities"]])
                    if data.get("confidence"):
                        result.confidence = data["confidence"]
                except json.JSONDecodeError:
                    logger.debug("llm_intent_json_parse_failed")

        except Exception:
            logger.debug("llm_intent_enhance_failed", exc_info=True)

        return result


# ── 全局单例 ──

from src.infra.singleton import Singleton

_intent_engine = Singleton(IntentEngine)


def get_intent_engine() -> IntentEngine:
    """获取意图引擎实例"""
    return _intent_engine.get()


def reset_intent_engine() -> None:
    """重置意图引擎"""
    _intent_engine.reset()


# ── 向后兼容API ──


def detect_intent(text: str, history: list[dict] | None = None) -> dict:
    """简化的意图检测API（向后兼容）"""
    engine = get_intent_engine()
    result = engine.parse(text, history)

    return {
        "intents": [{"type": i.intent_type, "confidence": i.confidence} for i in result.intents],
        "entities": [{"type": e.type, "value": e.value} for e in result.entities],
        "confidence": result.confidence,
        "main_intent": result.intents[0].intent_type if result.intents else IntentType.UNKNOWN,
    }
