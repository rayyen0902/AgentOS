"""
Reflection Agent — 异步 LLM 分析 Agent 表现
严格对应 Step 8 文档 8.1

触发条件:
- 配药师 workshop_card 推送完成 → 触发
- 识肤师 skin_report_card 推送完成 → 触发
- 问卷师 7 步完成 → 触发
- 前台 Agent 直出（无子 Agent） → 不触发
- Agent 超时/报错 → 不触发（记录 Observation 即可）

运行方式: asyncio.create_task，不阻塞主流程
模型: Pro LLM
失败处理: 不影响用户体验，只记录日志
输出: 写入 agent_audit_log 表
"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field

from app.agents.base import SessionContext, AgentResult
from app.agents.llm_util import llm_chat
from config import settings
from db_util import db
from app.observation.telemetry import telemetry

logger = logging.getLogger(__name__)

# ============================================================
# Reflection 数据模型
# ============================================================


@dataclass
class Reflection:
    """Reflection 分析结果"""
    satisfaction: str  # high | medium | low
    lesson: str  # 学到的经验/改进建议
    rule_candidate: str | None = None  # 新规则候选
    should_escalate: bool = False  # 是否需要升级
    risk_level: str = "none"  # none | low | medium | high | emergency
    raw_analysis: dict = field(default_factory=dict)


# ============================================================
# 触发条件判断
# ============================================================

REFLECTION_TRIGGER_SOURCES = {
    "workshop_card",      # 配药师推送完成
    "skin_report_card",   # 识肤师推送完成
    "diagnosis_7step",    # 问卷师 7 步完成
}


def should_trigger_reflection(result: AgentResult, agent_name: str) -> bool:
    """
    判断是否应触发 Reflection。

    触发条件（文档 8.1 表格）:
    - 配药师 workshop_card 推送完成 → 是
    - 识肤师 skin_report_card 推送完成 → 是
    - 问卷师 7 步完成 → 是
    - 前台 Agent 直出（无子 Agent） → 否
    - Agent 超时/报错 → 否
    """
    # 超时/报错 → 不触发
    if result.error is not None:
        logger.info(f"[Reflection] skip: agent={agent_name} has error={result.error}")
        return False

    # 有 card 且 type 匹配 → 触发
    if result.card is not None and result.card.type in REFLECTION_TRIGGER_SOURCES:
        logger.info(f"[Reflection] trigger: card_type={result.card.type}")
        return True

    # 问卷师 7 步完成（通过 state 中的 diagnosis_step 字段判断）
    # S8-08 修复: diagnosis_agent 存在 agent_state["diagnosis_step"]，不是 state.phase/step
    if agent_name in ("diagnosis", "问卷师"):
        diagnosis_step = result.state.get("diagnosis_step", 0)
        if diagnosis_step >= 7:
            logger.info(f"[Reflection] trigger: diagnosis completed 7+ steps (diagnosis_step={diagnosis_step})")
            return True

    # 其他 case（包括前台直出）→ 不触发
    return False


# ============================================================
# Reflection Agent
# ============================================================


class ReflectionAgent:
    """
    Reflection Agent — 异步分析 Agent 表现，不阻塞主流程。

    使用 Pro LLM 分析：
    - 用户输入 vs Agent 输出匹配度
    - 用户满意度评估
    - 经验教训总结
    - 风险检测（严重风险时 should_escalate=True）
    """

    name: str = "reflection"

    REFLECTION_SYSTEM_PROMPT = """你是一名护肤品 AI Agent 系统的质量评估专家。
你的任务是分析一个 Agent 回合的表现，给出客观评价。

请严格按以下 JSON 格式输出分析结果：
{
  "satisfaction": "high|medium|low",
  "lesson": "本回合的经验教训（一句话）",
  "new_rule": "如果可以抽取一条新规则，写在这里，否则填 null",
  "risk_level": "none|low|medium|high|emergency",
  "risk_detail": "风险描述，无风险时填 null"
}

评估维度：
1. 满意度: Agent 的回复是否准确、相关、有帮助
2. 经验: 什么做得好/不好？什么可以改进？
3. 规则: 是否有新的模式/规则可以固化到知识库？
4. 风险: 用户是否有安全风险（过敏、不良反应、医疗诉求等）？

风险判定标准：
- none: 无风险
- low: 轻微不适描述
- medium: 成分过敏确认
- high: 红肿/刺痛/起疹/投诉/退款/法律威胁/处方药请求
- emergency: 烂脸/严重不良反应"""

    async def reflect(
        self,
        ctx: SessionContext,
        result: AgentResult,
        agent_name: str,
        tool_calls: list[str] | None = None,
    ) -> Reflection:
        """
        对 Agent 回合进行 Reflection 分析。

        Args:
            ctx: 会话上下文
            result: Agent 执行结果
            agent_name: Agent 名称（配药师/问卷师/识肤师等）
            tool_calls: 本回合调用的工具列表

        Returns:
            Reflection 分析结果
        """
        t0 = time.time()

        # 构建分析提示
        user_prompt = f"""请分析以下 Agent 回合：

【用户输入】
{ctx.input}

【Agent 名称】
{agent_name}

【Agent 回复】
{result.reply}

【调用的工具】
{json.dumps(tool_calls or [], ensure_ascii=False)}

【执行结果】
- 是否有 Card 推送: {result.card is not None}
- Card 类型: {result.card.type if result.card else '无'}
- 是否有中断: {result.interrupt is not None}
- 错误信息: {result.error or '无'}

请给出你的分析。"""

        try:
            raw_response = await llm_chat(
                model=settings.LLM_PRO_MODEL,
                system_prompt=self.REFLECTION_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                timeout_s=30.0,
                json_mode=True,
                temperature=0.3,
                max_tokens=1024,
            )

            # 解析 LLM 输出
            analysis = json.loads(raw_response)

            # 判断是否需要升级（risk_level 为 high 或 emergency）
            risk_level = analysis.get("risk_level", "none")
            should_escalate = risk_level in ("high", "emergency")

            reflection = Reflection(
                satisfaction=analysis.get("satisfaction", "medium"),
                lesson=analysis.get("lesson", ""),
                rule_candidate=analysis.get("new_rule"),
                should_escalate=should_escalate,
                risk_level=risk_level,
                raw_analysis=analysis,
            )

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"[Reflection] LLM output parse error: {e}, raw={raw_response}")
            reflection = Reflection(
                satisfaction="medium",
                lesson=f"Reflection 解析失败: {e}",
                rule_candidate=None,
                should_escalate=False,
                risk_level="none",
            )

        elapsed_ms = int((time.time() - t0) * 1000)
        logger.info(
            f"[Reflection] agent={agent_name} satisfaction={reflection.satisfaction} "
            f"risk={reflection.risk_level} escalate={reflection.should_escalate} "
            f"elapsed={elapsed_ms}ms"
        )

        return reflection

    async def reflect_and_persist(
        self,
        ctx: SessionContext,
        result: AgentResult,
        agent_name: str,
        tool_calls: list[str] | None = None,
    ) -> Reflection | None:
        """
        执行 Reflection 并写入 agent_audit_log。
        失败不影响主流程。

        Returns:
            Reflection 对象，失败时返回 None
        """
        try:
            reflection = await self.reflect(ctx, result, agent_name, tool_calls)

            # 写入 agent_audit_log
            event_data = {
                "satisfaction": reflection.satisfaction,
                "lesson": reflection.lesson,
                "rule_candidate": reflection.rule_candidate,
                "risk_level": reflection.risk_level,
                "should_escalate": reflection.should_escalate,
                "user_input": ctx.input[:500],
                "agent_reply": result.reply[:500],
                "agent_name": agent_name,
                "tool_calls": tool_calls or [],
            }

            await db.execute(
                """
                INSERT INTO agent_audit_log (session_id, agent_name, event_type, event_data)
                VALUES ($1, $2, $3, $4)
                """,
                ctx.session_id,
                f"reflection:{agent_name}",     # S8-09 修复: 记录具体 agent_name 而非硬编码 "reflection"
                "reflection_complete",
                json.dumps(event_data, ensure_ascii=False),
            )

            logger.info(
                f"[Reflection] persisted: session={ctx.session_id} "
                f"agent={agent_name} satisfaction={reflection.satisfaction}"
            )

            return reflection

        except Exception as e:
            logger.error(f"[Reflection] failed for session={ctx.session_id}: {e}")
            # 失败不影响主流程
            return None


# ============================================================
# 异步触发入口
# ============================================================


async def trigger_reflection_async(
    ctx: SessionContext,
    result: AgentResult,
    agent_name: str,
    tool_calls: list[str] | None = None,
) -> None:
    """
    异步触发 Reflection（不阻塞主流程）。
    使用 asyncio.create_task 在后台运行。

    S8-01: 稳定 API 签名 — (ctx, result, agent_name) 三个必选参数是 Step 6 及各
    Agent 调用方（diagnosis_agent, workshop_agent, photo_analyst_agent, routes.py）
    约定的接口。tool_calls 为可选参数，仅在调用方记录了工具调用时传入。

    用法（在 Agent 完成时调用）:
        asyncio.create_task(trigger_reflection_async(ctx, result, agent_name))
    """
    agent = ReflectionAgent()

    # 检查是否应触发
    if not should_trigger_reflection(result, agent_name):
        logger.debug(f"[Reflection] not triggered for agent={agent_name}")
        return

    logger.info(f"[Reflection] starting async reflection for session={ctx.session_id} agent={agent_name}")

    reflection = await agent.reflect_and_persist(ctx, result, agent_name, tool_calls)

    # 如果 Reflection 检测到高风险 → 需要升级
    if reflection is not None and reflection.should_escalate:
        logger.warning(
            f"[Reflection] HIGH RISK detected: session={ctx.session_id} "
            f"risk={reflection.risk_level}"
        )

    # Step 8.2: Reflection 完成后总是触发 Memory Consolidation（异步，不阻塞）
    from app.agents.memory_consolidation import trigger_memory_consolidation_async
    asyncio.create_task(
        trigger_memory_consolidation_async(ctx.user_id, ctx.tenant_id)
    )


# 全局单例
reflection_agent = ReflectionAgent()
