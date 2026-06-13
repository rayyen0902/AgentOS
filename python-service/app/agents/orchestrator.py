"""
Orchestrator — 前台 Agent + 意图路由 (Step 6A)

职责:
- 接收用户消息 → 意图分类 → 委派子 Agent 或直接回复
- 模型: Flash LLM (不可中断)
- 不委派子 Agent 时自行回复
- 子 Agent 超时 + 并发控制
"""
import asyncio
import json
import logging
import time
from typing import Any

from app.agents.base import (
    AgentResult,
    CardPayload,
    InterruptRequest,
    SessionContext,
    StatusEvent,
)
from app.agents.llm_util import llm_chat
from app.agents.shared_util import now_iso
from app.identity.registry import CAPABILITY_REGISTRY
from config import settings

logger = logging.getLogger(__name__)

# ── 意图分类系统提示 ──
INTENT_CLASSIFY_SYSTEM_PROMPT = """你是 AgentOS 的前台路由 Agent。
根据用户消息，输出严格的 JSON 格式意图分类结果，不要输出其他内容。

意图类别 (intent):
- recommend_product: 推荐产品、买什么、选哪个、什么适合我
- skin_diagnosis: 肤质检测、做问卷、测一测、分析皮肤
- photo_analysis: 拍照、看皮肤、帮我看看照片
- daily_schedule: 日报、今天怎么护肤、明天护肤计划
- product_add: 录入产品、添加产品、我在用、记录产品
- knowledge_query: 什么是、成分、功效、适不适合
- chat: 聊天、问候、问进度、感谢、其他对话

输出格式:
{
  "intent": "...",
  "confidence": 0.0-1.0,
  "sub_intent": "...",
  "extracted_entities": {},
  "immediate_reply": "..."
}

注意:
- 若 confidence < 0.6，immediate_reply 应有澄清追问
- extracted_entities 从用户消息中提取关键实体（如 skin_concern, product_category, ingredient_name）
- immediate_reply 为给用户的即时安抚回复"""


async def classify_intent(user_input: str) -> dict:
    """调用 Flash LLM 进行意图分类，3s 超时"""
    raw = None
    try:
        raw = await llm_chat(
            model=settings.LLM_FLASH_MODEL,
            system_prompt=INTENT_CLASSIFY_SYSTEM_PROMPT,
            user_prompt=user_input,
            timeout_s=3.0,
            json_mode=True,
            temperature=0.1,
            max_tokens=512,
        )
        result = json.loads(raw)
        return result
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"[classify_intent] parse failed: {e}, raw={raw or 'N/A'}")
        return {
            "intent": "chat",
            "confidence": 0.3,
            "sub_intent": "",
            "extracted_entities": {},
            "immediate_reply": "收到，让我想想~",
        }


# ── 路由表 —— 严格对应 Step 6A 文档 ──
# intent -> (agent_type | tool_name | None)
ROUTING_TABLE: dict[str, str | None] = {
    "recommend_product": "workshop",
    "skin_diagnosis": "diagnosis",
    "photo_analysis": "photo_analyst",
    "daily_schedule": "copywriter",
    "product_add": "product_crud",       # 直接调用 Tool，不委派 Agent
    "knowledge_query": "rag_search",     # 直接调用 Tool，不委派 Agent
    "chat": None,                        # 前台 Agent 直接回复
}


async def run_orchestrator(ctx: SessionContext, input: str) -> AgentResult:
    """
    前台 Agent 主流程:
    0. 入口 stage 检查 (S6-04 escalated / S6-12 agent_running / S6-13 agent_interrupted)
    1. 意图分类 (Flash LLM, 3s 超时)
    2. 若 confidence < 0.6 → 直接对话澄清
    3. 根据路由表委派子 Agent 或调用 Tool 或自行回复
    """
    events: list[StatusEvent] = []
    t_start = time.time()

    # ── S6-04: 入口检查 escalated 状态 ──
    stage = ctx.agent_state.get("stage", "idle")
    if stage == "escalated":
        events.append(StatusEvent(
            seq=0, source="agent:orchestrator",
            status="done", label="已转人工，消息仅记录",
            created_at=_now(),
        ))
        return AgentResult(
            state={"phase": "escalated", "stage": "escalated"},
            reply="您的问题已转接至人工客服，请耐心等待。如需继续使用 AI 服务，请重新开始会话~",
            events=events,
            done=True,
        )

    # ── S6-12: agent_running 时，所有消息（含直接 Tool）统一丢弃 ──
    if stage == "agent_running":
        events.append(StatusEvent(
            seq=0, source="agent:orchestrator",
            status="done", label="Agent 正忙，消息被丢弃",
            created_at=_now(),
        ))
        return AgentResult(
            state={"phase": "busy"},
            reply="正在处理上一条消息，稍等~",
            events=events,
            done=True,
        )

    # ── S6-13: agent_interrupted 时，发 chat 消息清理中断状态 ──
    if stage == "agent_interrupted":
        # 先做意图分类判断
        intent_result = await classify_intent(input)
        intent = intent_result.get("intent", "chat")
        if intent == "chat":
            # 用户发聊天消息，清理中断状态
            return AgentResult(
                state={"stage": "idle", "current_agent": None},
                reply="好的，已退出当前任务。有什么可以帮您的吗？~",
                events=events,
                done=True,
            )
        # 非 chat → 正常 resume 流程
        agent_type = ctx.agent_state.get("current_agent", "")
        return await resume_agent(ctx, agent_type, input, events, 0)

    # Step 1: 意图分类
    seq = 0
    events.append(StatusEvent(
        seq=seq, source="agent:orchestrator",
        status="running", label="正在进行意图识别...",
        created_at=_now(),
    ))

    intent_result = await classify_intent(input)
    intent = intent_result.get("intent", "chat")
    confidence = intent_result.get("confidence", 0.0)
    immediate_reply = intent_result.get("immediate_reply", "收到~")

    seq += 1
    events.append(StatusEvent(
        seq=seq, source="agent:orchestrator",
        status="done",
        label=f"意图识别完成: {intent} (confidence={confidence:.2f})",
        duration_ms=int((time.time() - t_start) * 1000),
        created_at=_now(),
    ))

    # 若 confidence < 0.6 → 前台 Agent 直接对话澄清，不委派子 Agent
    if confidence < 0.6:
        reply = immediate_reply or "不太确定您的意思，能再说详细一点吗？"
        events.append(StatusEvent(
            seq=seq + 1, source="agent:orchestrator",
            status="done",
            label="置信度不足，直接对话澄清",
            duration_ms=0,
            created_at=_now(),
        ))
        return AgentResult(
            state={"phase": "clarify", "intent": intent, "confidence": confidence},
            reply=reply,
            events=events,
            done=True,
        )

    # 查找路由
    target = ROUTING_TABLE.get(intent)

    if target is None:
        # 聊天/问候 → 前台 Agent 直接回复
        return await _direct_chat_reply(ctx, input, events, seq)

    if target == "product_crud":
        # 直接调用 product_crud Tool
        return await _direct_tool_product_add(ctx, input, intent_result, events, seq)

    if target == "rag_search":
        # 直接调用 rag_search Tool
        return await _direct_tool_rag(ctx, input, intent_result, events, seq)

    # 委派子 Agent
    agent_type = target
    return await _delegate_to_agent(ctx, input, agent_type, intent_result, events, seq)


async def _direct_chat_reply(
    ctx: SessionContext, input: str,
    events: list[StatusEvent], seq: int,
) -> AgentResult:
    """前台 Agent 直接处理聊天/问候"""
    try:
        reply = await llm_chat(
            model=settings.LLM_FLASH_MODEL,
            system_prompt="你是肤小护，一个温暖专业的护肤品 AI 助手。用亲切自然的语气回复用户。回复简洁，不超过 100 字。",
            user_prompt=input,
            timeout_s=3.0,
            temperature=0.7,
            max_tokens=256,
        )
    except Exception:
        reply = "你好呀~ 有什么护肤问题可以随时问我！"

    events.append(StatusEvent(
        seq=seq + 1, source="agent:orchestrator",
        status="done", label="前台直出回复",
        created_at=_now(),
    ))
    return AgentResult(
        state={"phase": "direct_chat"},
        reply=reply,
        events=events,
        done=True,
    )


async def _direct_tool_product_add(
    ctx: SessionContext, input: str,
    intent_result: dict, events: list[StatusEvent], seq: int,
) -> AgentResult:
    """直接调用 product_crud Tool 录入产品"""
    from app.agents.tool_invoker import product_crud

    entities = intent_result.get("extracted_entities", {})
    data = {
        "name": entities.get("product_name", ""),
        "category": entities.get("product_category", ""),
        "brand": entities.get("brand", ""),
        "description": entities.get("description", input),
    }

    events.append(StatusEvent(
        seq=seq + 1, source="tool:product_crud",
        status="running", label="正在录入产品信息...",
        created_at=_now(),
    ))

    result = await product_crud(
        action="create",
        tenant_id=ctx.tenant_id,
        data=data,
    )

    events.append(StatusEvent(
        seq=seq + 2, source="tool:product_crud",
        status="done" if result.success else "error",
        label=f"产品{'录入成功' if result.success else '录入失败'}",
        created_at=_now(),
    ))

    if result.success and result.products:
        p = result.products[0]
        reply = f"已记录产品「{p.name}」({p.brand})，后续推荐时会考虑它的成分哦~"
    else:
        reply = "录入产品时遇到问题，请稍后再试~"

    return AgentResult(
        state={"phase": "tool_direct", "tool": "product_crud"},
        reply=reply,
        events=events,
        done=True,
        error=result.error,
    )


async def _direct_tool_rag(
    ctx: SessionContext, input: str,
    intent_result: dict, events: list[StatusEvent], seq: int,
) -> AgentResult:
    """直接调用 rag_search Tool 检索知识"""
    from app.agents.tool_invoker import rag_search

    entities = intent_result.get("extracted_entities", {})
    query = entities.get("ingredient_name") or entities.get("product_name") or input

    events.append(StatusEvent(
        seq=seq + 1, source="tool:rag_search",
        status="running", label="正在检索护肤知识...",
        created_at=_now(),
    ))

    result = await rag_search(
        query=query,
        tenant_id=ctx.tenant_id,
        top_k=3,
        search_type="hybrid",
    )

    events.append(StatusEvent(
        seq=seq + 2, source="tool:rag_search",
        status="done", label=f"检索完成 (共 {result.total} 条)",
        created_at=_now(),
    ))

    if result.items:
        lines = ["根据知识库检索结果:"]
        for item in result.items:
            if item.description:
                lines.append(f"• {item.name}: {item.description[:100]}")
        reply = "\n".join(lines)
    else:
        # 无结果，前台 Agent 自行回复
        try:
            reply = await llm_chat(
                model=settings.LLM_FLASH_MODEL,
                system_prompt="你是肤小护。用户问了一个护肤问题，但你未在知识库中找到匹配答案。请基于常识给出通用建议，不超过 100 字，并在末尾建议咨询专业人士。",
                user_prompt=input,
                timeout_s=3.0,
                temperature=0.5,
                max_tokens=256,
            )
        except Exception:
            reply = "这个问题我暂时无法准确回答，建议咨询专业皮肤科医生哦~"

    return AgentResult(
        state={"phase": "tool_direct", "tool": "rag_search"},
        reply=reply,
        events=events,
        done=True,
    )


async def _delegate_to_agent(
    ctx: SessionContext, input: str,
    agent_type: str, intent_result: dict,
    events: list[StatusEvent], seq: int,
) -> AgentResult:
    """
    委派给子 Agent，带并发锁检查和超时控制。
    严格对应 Step 6 6.1 并发控制规范:
    - 同一 session_id 同一时刻只允许一个 Agent 运行
    - stage = agent_running → 回复"正在处理，稍等~"
    - stage = agent_interrupted → route to agent.resume()
    """
    from app.agents.workshop_agent import WorkshopAgent
    from app.agents.diagnosis_agent import DiagnosisAgent
    from app.agents.photo_analyst_agent import PhotoAnalystAgent
    from app.agents.copywriter_agent import CopywriterAgent

    agent_info = CAPABILITY_REGISTRY.get(agent_type, {})
    timeout_s = agent_info.get("timeout_s", 30)
    display_name = agent_info.get("name", agent_type)

    # 检查 session stage
    stage = ctx.agent_state.get("stage", "idle")

    if stage == "agent_running":
        # 正在处理中，不启动新 Agent
        events.append(StatusEvent(
            seq=seq + 1, source="agent:orchestrator",
            status="done", label="Agent 正忙，消息被丢弃",
            created_at=_now(),
        ))
        return AgentResult(
            state={"phase": "busy"},
            reply="正在处理上一条消息，稍等~",
            events=events,
            done=True,
        )

    if stage == "agent_interrupted":
        # 中断恢复 → 路由至 agent.resume()
        return await resume_agent(ctx, agent_type, input, events, seq)

    # ── S6-05: 子 Agent 启动前调 escalate 检查 ──
    from app.agents.escalation import check_and_escalate
    escal_result, is_escalated = await check_and_escalate(
        ctx.session_id, input,
    )
    if is_escalated and escal_result.should_block:
        events.append(StatusEvent(
            seq=seq + 1, source="agent:orchestrator",
            status="done", label=f"触发人工升级: {escal_result.matched_rule}",
            created_at=_now(),
        ))
        return AgentResult(
            state={"stage": "escalated", "current_agent": None},
            reply=escal_result.reply_override or "您的问题已转接至人工客服，请稍候~",
            events=events,
            done=True,
        )
    if escal_result.action.value == "reject_and_advise":
        return AgentResult(
            state={"stage": "idle", "current_agent": None},
            reply=escal_result.reply_override or "护肤品不能替代药品，建议咨询皮肤科医生获取专业诊断。",
            events=events,
            done=True,
        )

    # 正常委派
    agents_map = {
        "workshop": WorkshopAgent(),
        "diagnosis": DiagnosisAgent(),
        "photo_analyst": PhotoAnalystAgent(),
        "copywriter": CopywriterAgent(),
    }

    agent = agents_map.get(agent_type)
    if agent is None:
        return AgentResult(
            state={"phase": "error"},
            reply=f"{display_name}暂不可用，稍后再试~",
            events=events,
            done=True,
            error=f"agent {agent_type} not found",
        )

    # 设置 agent_state 为 agent_running
    ctx.agent_state = {
        "stage": "agent_running",
        "current_agent": agent_type,
        "intent": intent_result,
    }

    events.append(StatusEvent(
        seq=seq + 1, source=f"agent:{agent_type}",
        status="running",
        label=f"{immediate_reply}" if (immediate_reply := intent_result.get("immediate_reply", "")) else f"正在委托{display_name}...",
        created_at=_now(),
    ))

    try:
        result = await asyncio.wait_for(
            agent.run(ctx, input),
            timeout=timeout_s,
        )
        result.events = events + result.events
        if result.interrupt:
            # Agent 中断 → 更新 stage 为 agent_interrupted
            # 同时设置 interrupt_timeout_start 用于 5 分钟后超时兜底
            result.state["stage"] = "agent_interrupted"
            result.state["current_agent"] = agent_type
            result.state["interrupt_started_at"] = _now()
        else:
            result.state["stage"] = "idle"
            result.state["current_agent"] = None
        return result

    except asyncio.TimeoutError:
        # 子 Agent 超时 → 兜底回复
        logger.warning(f"[orchestrator] {agent_type} timeout after {timeout_s}s")
        events.append(StatusEvent(
            seq=seq + 2, source=f"agent:{agent_type}",
            status="error",
            label=f"{display_name}分析超时",
            created_at=_now(),
        ))
        return AgentResult(
            state={"phase": "timeout", "current_agent": None},
            reply=f"分析超时，已记录，稍后重试~",
            events=events,
            done=True,
            error=f"agent {agent_type} timeout",
        )

    except Exception as e:
        logger.error(f"[orchestrator] {agent_type} error: {e}")
        return AgentResult(
            state={"phase": "error", "current_agent": None},
            reply=f"{display_name}暂时不可用，请稍后再试~",
            events=events,
            done=True,
            error=str(e),
        )


async def resume_agent(
    ctx: SessionContext,
    agent_type: str,
    input: str,
    events: list[StatusEvent],
    seq: int,
) -> AgentResult:
    """中断恢复: 路由至 agent.resume()"""
    from app.agents.workshop_agent import WorkshopAgent
    from app.agents.diagnosis_agent import DiagnosisAgent
    from app.agents.photo_analyst_agent import PhotoAnalystAgent
    from app.agents.copywriter_agent import CopywriterAgent

    agents_map = {
        "workshop": WorkshopAgent(),
        "diagnosis": DiagnosisAgent(),
        "photo_analyst": PhotoAnalystAgent(),
        "copywriter": CopywriterAgent(),
    }

    agent = agents_map.get(agent_type)
    if agent is None:
        return AgentResult(
            state={"phase": "error"},
            reply="Agent 暂不可用，稍后再试~",
            events=events,
            done=True,
            error=f"agent {agent_type} not found",
        )

    agent_info = CAPABILITY_REGISTRY.get(agent_type, {})
    timeout_s = agent_info.get("timeout_s", 30)

    events.append(StatusEvent(
        seq=seq + 1, source=f"agent:{agent_type}",
        status="running",
        label="中断恢复，继续执行",
        created_at=_now(),
    ))

    try:
        result = await asyncio.wait_for(
            agent.resume(ctx, input),
            timeout=timeout_s,
        )
        result.events = events + result.events
        if result.interrupt:
            result.state["stage"] = "agent_interrupted"
        else:
            result.state["stage"] = "idle"
            result.state["current_agent"] = None
        return result

    except asyncio.TimeoutError:
        return AgentResult(
            state={"phase": "timeout"},
            reply="分析超时，已记录，稍后重试~",
            events=events,
            done=True,
            error=f"agent {agent_type} resume timeout",
        )
    except Exception as e:
        return AgentResult(
            state={"phase": "error"},
            reply="服务暂时不可用，请稍后再试~",
            events=events,
            done=True,
            error=str(e),
        )


def _now() -> str:
    return now_iso()
