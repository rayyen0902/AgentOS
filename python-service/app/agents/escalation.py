"""
Human Escalation 规则引擎
严格对应 Step 8 文档 8.3

升级规则（5 级）:
- urgent: 过敏反应描述（红肿/刺痛/起疹） → 转人工 + 站内告警
- emergency: 烂脸/严重不良反应 → 转人工 + 电话/短信通知
- high: 投诉/退款/法律威胁 → 转人工客服
- high: 医疗建议请求（处方药/皮肤病） → 拒答 + 建议就医
- medium: 成分过敏确认 → 中断 + 人工确认

检测时机: 前台 Agent 意图分类完成后，子 Agent 启动前
检测方式: 规则匹配（关键词 + 正则）+ Flash LLM 二次确认（高敏感场景）
转人工后: SessionState.stage → escalated，不再接受 Agent 处理，只记录消息
恢复: 管理员在后台手动将 stage 重置为 idle
"""
import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.agents.llm_util import llm_chat
from config import settings
from db_util import db

logger = logging.getLogger(__name__)


# ============================================================
# 升级等级
# ============================================================

class EscalationLevel(Enum):
    NONE = "none"           # 无需升级
    MEDIUM = "medium"       # 成分过敏确认 → 中断 + 人工确认
    HIGH = "high"           # 投诉/退款/法律威胁/处方药 → 转人工/拒答
    URGENT = "urgent"       # 过敏反应描述 → 转人工 + 站内告警
    EMERGENCY = "emergency" # 烂脸/严重不良反应 → 转人工 + 电话/短信


class EscalationAction(Enum):
    NONE = "none"
    INTERRUPT = "interrupt"                  # 中断 + 人工确认
    ESCALATE_SERVICE = "escalate_service"     # 转人工客服
    ESCALATE_ALERT = "escalate_alert"         # 转人工 + 站内告警
    ESCALATE_URGENT = "escalate_urgent"       # 转人工 + 电话/短信通知
    REJECT_AND_ADVISE = "reject_and_advise"   # 拒答 + 建议就医


# ============================================================
# 数据模型
# ============================================================


@dataclass
class EscalationResult:
    """升级检测结果"""
    level: EscalationLevel
    action: EscalationAction
    matched_rule: str  # 匹配的规则描述
    reason: str  # 触发原因
    should_block: bool = False  # 是否阻断后续处理
    reply_override: str | None = None  # 覆盖回复（reject_and_advise 时使用）


# ============================================================
# 升级规则定义（文档 8.3）
# ============================================================


@dataclass
class EscalationRule:
    """单条升级规则"""
    condition: str          # 规则描述
    level: EscalationLevel
    action: EscalationAction
    keywords: list[str]     # 关键词列表
    patterns: list[str]     # 正则表达式列表
    llm_verify: bool = False  # 是否需要 Flash LLM 二次确认
    should_block: bool = False
    reply_override: str | None = None


# 规则表 — 严格对应 Step 8 文档 8.3
ESCALATION_RULES: list[EscalationRule] = [
    EscalationRule(
        condition="过敏反应描述（红肿/刺痛/起疹）",
        level=EscalationLevel.URGENT,
        action=EscalationAction.ESCALATE_ALERT,
        keywords=["红肿", "刺痛", "起疹", "起皮", "瘙痒", "发痒", "灼热", "发热"],
        patterns=[
            r"红.?肿",
            r"刺.?痛",
            r"起.?疹",
            r"(过敏|敏感).*反应",
            r"(皮肤|脸).*(红|肿|痛|痒)",
        ],
        llm_verify=True,
        should_block=True,
        reply_override="检测到您描述的过敏反应症状，为安全起见已暂停 AI 服务。我们的护肤顾问将尽快联系您，请耐心等待。",
    ),
    EscalationRule(
        condition="烂脸/严重不良反应",
        level=EscalationLevel.EMERGENCY,
        action=EscalationAction.ESCALATE_URGENT,
        keywords=["烂脸", "毁容", "严重过敏", "呼吸困难", "休克", "溃烂", "水泡"],
        patterns=[
            r"烂.?脸",
            r"毁.?容",
            r"(严重|重度|急性).*(过敏|反应)",
            r"呼吸.?困难",
            r"休.?克",
            r"溃.?烂",
            r"水.?泡",
        ],
        llm_verify=True,
        should_block=True,
        reply_override="您描述的症状属于严重不良反应，请立即停止使用产品并就医。我们已触发紧急响应，专业顾问将尽快与您联系。",
    ),
    EscalationRule(
        condition="投诉/退款/法律威胁",
        level=EscalationLevel.HIGH,
        action=EscalationAction.ESCALATE_SERVICE,
        keywords=["投诉", "退款", "赔偿", "律师", "起诉", "消协", "12315", "维权"],
        patterns=[
            r"(我要|想).*投诉",
            r"退款",
            r"赔偿",
            r"(找|请).*律师",
            r"起诉",
            r"12315",
            r"消协",
            r"维权",
        ],
        llm_verify=False,
        should_block=True,
        reply_override="我们非常重视您的反馈，已将您的问题转接至人工客服，请稍候。",
    ),
    EscalationRule(
        condition="医疗建议请求（处方药/皮肤病）",
        level=EscalationLevel.HIGH,
        action=EscalationAction.REJECT_AND_ADVISE,
        keywords=["处方药", "皮肤病", "湿疹", "痤疮", "银屑病", "皮炎", "皮肤癌",
                  "药膏", "抗生素", "激素", "维A酸", "异维A酸"],
        patterns=[
            r"处.?方.?药",
            r"(皮肤|皮).*病",
            r"(开|配|买).*(药|膏)",
            r"(湿疹|痤疮|银屑|皮炎|癣|疣|疱疹)",
            r"(需要|推荐).*药",
        ],
        llm_verify=True,
        should_block=True,
        reply_override="护肤品不能替代药品。您描述的问题建议咨询皮肤科医生获取专业诊断和处方。我们可以为您推荐适合日常护理的产品，但不能提供医疗建议。",
    ),
    EscalationRule(
        condition="成分过敏确认",
        level=EscalationLevel.MEDIUM,
        action=EscalationAction.INTERRUPT,
        keywords=["过敏", "过敏原", "不耐受", "成分不耐受"],
        patterns=[
            r"(对|不能|无法).*(成分|耐受)",
            r"过.?敏.?原",
            r"(已知|确认).*过敏",
        ],
        llm_verify=False,
        should_block=True,
        reply_override=None,  # 中断后等待人工确认
    ),
]


# ============================================================
# Flash LLM 二次确认
# ============================================================


ESCALATION_VERIFY_PROMPT = """你是一个护肤品客服安全审核助手。
你的任务是判断用户消息是否真实触发了安全升级条件。

请严格按以下 JSON 格式输出：
{
  "is_real": true/false,
  "reason": "判断理由（一句话）",
  "severity": "none|medium|high|urgent|emergency"
}

判断标准：
- 用户确实描述了相关的症状/诉求 → is_real=true
- 用户只是询问一般性问题（如"什么是红肿"） → is_real=false
- 用户在描述他人/转述 → is_real=false
- 无法确定 → is_real=false（宁可漏判不可误判）"""


async def llm_verify_escalation(
    user_input: str, rule: EscalationRule
) -> bool:
    """
    使用 Flash LLM 对高敏感场景进行二次确认。
    返回 True 表示确认触发升级。
    """
    try:
        prompt = f"""请审核以下用户消息是否触发了安全升级条件。

【升级规则】
{rule.condition}

【用户消息】
{user_input}

请判断是否确实触发此升级条件。"""

        response = await llm_chat(
            model=settings.LLM_FLASH_MODEL,
            system_prompt=ESCALATION_VERIFY_PROMPT,
            user_prompt=prompt,
            timeout_s=10.0,
            json_mode=True,
            temperature=0.1,
            max_tokens=256,
        )

        result = json.loads(response)
        is_real = result.get("is_real", False)
        logger.info(
            f"[Escalation] LLM verify: rule={rule.condition[:30]} "
            f"is_real={is_real} reason={result.get('reason', '')}"
        )
        return is_real

    except (json.JSONDecodeError, KeyError) as e:
        logger.warning(f"[Escalation] LLM verify parse error: {e}")
        # 解析失败时，如果关键词命中 → 保守处理，确认触发
        return True
    except Exception as e:
        logger.error(f"[Escalation] LLM verify failed: {e}")
        # LLM 调用失败时，如果关键词命中 → 保守处理，确认触发
        return True


# ============================================================
# 规则引擎
# ============================================================


class HumanEscalationEngine:
    """
    Human Escalation 规则引擎。

    检测流程:
    1. 关键词 + 正则匹配 → 初筛
    2. 高敏感场景 → Flash LLM 二次确认
    3. 返回 EscalationResult
    """

    name: str = "human_escalation"

    async def check(self, user_input: str) -> EscalationResult:
        """
        检查用户输入是否需要人工升级。

        Args:
            user_input: 用户输入文本

        Returns:
            EscalationResult — 升级检测结果
        """
        user_input_lower = user_input.lower()

        # Step 1: 规则匹配
        matched_rules: list[EscalationRule] = []
        for rule in ESCALATION_RULES:
            # 关键词匹配
            keyword_hit = any(kw in user_input for kw in rule.keywords)
            # 正则匹配
            pattern_hit = any(
                re.search(pattern, user_input) for pattern in rule.patterns
            )
            if keyword_hit or pattern_hit:
                matched_rules.append(rule)

        if not matched_rules:
            return EscalationResult(
                level=EscalationLevel.NONE,
                action=EscalationAction.NONE,
                matched_rule="",
                reason="未匹配任何升级规则",
                should_block=False,
            )

        # Step 2: 取最高级别规则
        level_order = {
            EscalationLevel.EMERGENCY: 5,
            EscalationLevel.URGENT: 4,
            EscalationLevel.HIGH: 3,
            EscalationLevel.MEDIUM: 2,
            EscalationLevel.NONE: 0,
        }
        matched_rules.sort(key=lambda r: level_order.get(r.level, 0), reverse=True)
        top_rule = matched_rules[0]

        # Step 3: Flash LLM 二次确认（仅高敏感场景）
        is_confirmed = True
        if top_rule.llm_verify:
            is_confirmed = await llm_verify_escalation(user_input, top_rule)

        if not is_confirmed:
            logger.info(
                f"[Escalation] LLM rejected rule: {top_rule.condition[:50]}"
            )
            return EscalationResult(
                level=EscalationLevel.NONE,
                action=EscalationAction.NONE,
                matched_rule=top_rule.condition,
                reason="Flash LLM 二次确认未通过",
                should_block=False,
            )

        # Step 4: 构建结果
        result = EscalationResult(
            level=top_rule.level,
            action=top_rule.action,
            matched_rule=top_rule.condition,
            reason=f"关键词/正则命中: {top_rule.condition}",
            should_block=top_rule.should_block,
            reply_override=top_rule.reply_override,
        )

        logger.warning(
            f"[Escalation] TRIGGERED: level={result.level.value} "
            f"action={result.action.value} rule={result.matched_rule[:60]}"
        )

        return result

    async def escalate_session(
        self,
        session_id: str,
        user_input: str,
        escalation: EscalationResult,
    ) -> None:
        """
        将 session 标记为 escalated 状态，写入 agent_audit_log。
        """
        try:
            # 更新 session_states.stage → 'escalated'
            await db.execute(
                """
                UPDATE session_states
                SET stage = 'escalated',
                    error_info = $2,
                    updated_at = NOW()
                WHERE session_id = $1
                """,
                session_id,
                json.dumps({
                    "escalation_level": escalation.level.value,
                    "escalation_action": escalation.action.value,
                    "matched_rule": escalation.matched_rule,
                    "reason": escalation.reason,
                    "user_input_snippet": user_input[:200],
                }, ensure_ascii=False),
            )

            # 写入 audit_log
            await db.execute(
                """
                INSERT INTO agent_audit_log (session_id, agent_name, event_type, event_data)
                VALUES ($1, $2, $3, $4)
                """,
                session_id,
                "human_escalation",
                "escalation_triggered",
                json.dumps({
                    "level": escalation.level.value,
                    "action": escalation.action.value,
                    "matched_rule": escalation.matched_rule,
                    "reason": escalation.reason,
                    "should_block": escalation.should_block,
                    "user_input": user_input[:500],
                }, ensure_ascii=False),
            )

        except Exception as e:
            logger.error(f"[Escalation] failed to escalate session={session_id}: {e}")

    async def reset_session(self, session_id: str) -> bool:
        """
        管理员重置 session stage 为 idle。
        """
        try:
            result = await db.execute(
                """
                UPDATE session_states
                SET stage = 'idle',
                    error_info = NULL,
                    updated_at = NOW()
                WHERE session_id = $1 AND stage = 'escalated'
                """,
                session_id,
            )
            # result is a command tag like "UPDATE 1"
            affected = "UPDATE 1" in str(result) or "UPDATE 0" in str(result)
            logger.info(f"[Escalation] reset session={session_id} affected={affected}")
            return True
        except Exception as e:
            logger.error(f"[Escalation] failed to reset session={session_id}: {e}")
            return False

    async def is_session_escalated(self, session_id: str) -> bool:
        """
        检查 session 是否处于 escalated 状态。
        """
        try:
            row = await db.fetchrow(
                "SELECT stage FROM session_states WHERE session_id = $1",
                session_id,
            )
            if row is None:
                return False
            return row["stage"] == "escalated"
        except Exception as e:
            logger.error(f"[Escalation] failed to check session={session_id}: {e}")
            return False


# ============================================================
# 便捷函数
# ============================================================


async def check_escalation(user_input: str) -> EscalationResult:
    """快捷入口：检查用户输入是否需要升级"""
    engine = HumanEscalationEngine()
    return await engine.check(user_input)


async def check_and_escalate(
    session_id: str, user_input: str,
) -> tuple[EscalationResult, bool]:
    """
    检查 + 自动升级（一站式）。
    返回 (result, is_escalated)。

    用法（在 Agent 意图分类完成后调用）:
        result, is_escalated = await check_and_escalate(session_id, user_input)
        if is_escalated:
            return result.reply_override  # 直接返回覆盖回复
    """
    engine = HumanEscalationEngine()
    result = await engine.check(user_input)

    if result.should_block:
        await engine.escalate_session(session_id, user_input, result)
        return result, True

    return result, False


# 全局单例
escalation_engine = HumanEscalationEngine()
