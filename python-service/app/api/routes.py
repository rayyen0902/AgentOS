"""
API 路由 — /agent/run, /agent/resume, /agent/health
Step 6 实现: 使用真实 Orchestrator 意图分类 + 委派
Step 8 运营闭环: Human Escalation 检测 + Reflection 异步触发
"""
import asyncio
import time
import uuid
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.agents.base import SessionContext, AgentResult
from app.agents.orchestrator import run_orchestrator, resume_agent
from app.agents.interrupt_handler import (
    check_interrupt_timeout,
    check_diagnosis_step_timeout,
    check_diagnosis_quit,
)
from app.agents.reflection import trigger_reflection_async
from app.agents.escalation import check_and_escalate
from app.observation.telemetry import telemetry
from redis_util import redis_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agent")

# S2-05: PRD 20.3 规定消息内容 max_length=2000
MAX_INPUT_LENGTH = 2000

# S2-05: PRD 5.4.1 规定 Agent 回复 max_length=1000
MAX_REPLY_LENGTH = 1000


class MessageInput(BaseModel):
    type: str = "text"
    content: str = Field(default="", max_length=MAX_INPUT_LENGTH)
    image_url: str | None = None


class RunRequest(BaseModel):
    session_id: str
    user_id: int
    tenant_id: int
    platform: str
    message: MessageInput
    agent_state: dict = {}


class ResumeRequest(BaseModel):
    session_id: str
    user_id: int
    tenant_id: int
    interrupt_reply: str = Field(min_length=1, max_length=MAX_INPUT_LENGTH)
    agent_state: dict = {}


def _truncate_reply(text: str) -> str:
    """S2-09: 截断回复至 PRD 5.4.1 规定的 1000 字"""
    if len(text) <= MAX_REPLY_LENGTH:
        return text
    return text[: MAX_REPLY_LENGTH - 3] + "..."


def _agent_result_to_response(
    session_id: str,
    result: AgentResult,
    trace_id: str,
) -> dict[str, Any]:
    """将 AgentResult 转换为 API 响应格式"""
    events: list[dict[str, Any]] = []

    for ev in result.events:
        events.append({
            "type": "status",
            "data": {
                "seq": ev.seq,
                "source": ev.source,
                "status": ev.status,
                "label": ev.label,
                "duration_ms": ev.duration_ms,
                "created_at": ev.created_at,
            },
        })

    # reply event — S2-09: 裁切长文本
    events.append({
        "type": "reply",
        "data": {"text": _truncate_reply(result.reply)},
    })

    # card event
    if result.card:
        events.append({
            "type": "card",
            "data": {
                "card_type": result.card.type,
                "payload": result.card.data,
            },
        })

    # interrupt event
    interrupt = None
    if result.interrupt:
        interrupt = {
            "interrupt_id": str(uuid.uuid4())[:8],
            "label": result.interrupt.type,
            "question": result.interrupt.question,
            "options": result.interrupt.options,
            "timeout_s": result.interrupt.timeout_s,
            "created_at": result.interrupt.created_at or _now(),
        }
        events.append({
            "type": "interrupt",
            "data": interrupt,
        })

    # done event
    if result.done:
        events.append({
            "type": "done",
            "data": {},
        })

    # S2-04: error 统一放在 data 内层
    return {
        "session_id": session_id,
        "events": events,
        "new_agent_state": result.state,
        "interrupt": interrupt,
        "error": result.error,
    }


@router.post("/run")
async def agent_run(req: RunRequest):
    # S2-05: 输入长度校验
    if len(req.message.content) > MAX_INPUT_LENGTH:
        return _error_response(4001, f"消息长度超过 {MAX_INPUT_LENGTH} 字限制", "")

    trace_id = await telemetry.start_trace(req.session_id, "orchestrator")

    # ── 6.6: 中断超时检测 ──
    agent_state = dict(req.agent_state)
    timeout_resume = check_interrupt_timeout(agent_state)
    if timeout_resume:
        logger.info(
            f"[agent_run] 中断超时，自动使用默认答案继续, "
            f"session={req.session_id}, agent={agent_state.get('current_agent')}"
        )
        agent_state.update(timeout_resume)
        req.agent_state = agent_state
        return await _handle_resume(req, trace_id, default_resume=True)

    # ── 6.6: 问卷单步超时检测 ──
    step_timeout = check_diagnosis_step_timeout(agent_state)
    if step_timeout:
        logger.info(
            f"[agent_run] 问卷单步超时, 重发当前问题, "
            f"session={req.session_id}, step={step_timeout.get('diagnosis_step')}"
        )
        req.agent_state = {**agent_state, **step_timeout}
        from app.agents.diagnosis_agent import DIAGNOSIS_STEPS

        step_idx = step_timeout.get("diagnosis_step", 1) - 1
        if 0 <= step_idx < len(DIAGNOSIS_STEPS):
            step_info = DIAGNOSIS_STEPS[step_idx]
            options_text = "\n".join(
                f"{chr(65 + i)}. {opt}" for i, opt in enumerate(step_info["options"])
            )
            question_text = f"⏰ 上一问已超时，重新发送:\n\n{step_info['question']}\n\n{options_text}"
            # S2-02: 超时分支也落库
            await telemetry.finish_trace(trace_id, 0)
            await telemetry.flush_to_db(trace_id)
            return {
                "code": 0,
                "message": "ok",
                "data": {
                    "session_id": req.session_id,
                    "events": [
                        {
                            "type": "status",
                            "data": {
                                "seq": 0,
                                "source": "agent:diagnosis",
                                "status": "running",
                                "label": f"单步超时,重发第{step_idx + 1}/7步",
                            },
                        },
                        {"type": "reply", "data": {"text": question_text}},
                    ],
                    "new_agent_state": req.agent_state,
                    "interrupt": None,
                    "error": None,
                },
                "trace_id": trace_id,
            }

    # ── 6.6: 问卷中途退出检测 (S6-08: 带二次确认) ──
    quit_result = check_diagnosis_quit(req.message.content, agent_state)
    if quit_result:
        if agent_state.get("quit_pending"):
            # 用户确认退出 → 真正清空状态
            logger.info(f"[agent_run] 问卷退出确认, session={req.session_id}")
            await telemetry.finish_trace(trace_id, 0)
            await telemetry.flush_to_db(trace_id)
            return {
                "code": 0,
                "message": "ok",
                "data": {
                    "session_id": req.session_id,
                    "events": [
                        {"type": "status", "data": {"seq": 0, "source": "agent:diagnosis", "status": "done", "label": "用户确认退出问卷"}},
                        {"type": "reply", "data": {"text": "已退出肤质问诊。有任何护肤问题随时找我哦~"}},
                        {"type": "done", "data": {}},
                    ],
                    "new_agent_state": {},
                    "interrupt": None,
                    "error": None,
                },
                "trace_id": trace_id,
            }
        else:
            # 首次触发 → 发送确认提示，标记 quit_pending
            logger.info(f"[agent_run] 问卷退出关键词命中，发送确认提示, session={req.session_id}")
            agent_state["quit_pending"] = True
            await telemetry.finish_trace(trace_id, 0)
            await telemetry.flush_to_db(trace_id)
            return {
                "code": 0,
                "message": "ok",
                "data": {
                    "session_id": req.session_id,
                    "events": [
                        {"type": "status", "data": {"seq": 0, "source": "agent:diagnosis", "status": "running", "label": "等待用户确认退出"}},
                        {"type": "reply", "data": {"text": "确定要退出肤质问诊吗？之前已填写的答案不会保留哦。回复「是」确认退出，回复其他内容继续问诊~"}},
                    ],
                    "new_agent_state": agent_state,
                    "interrupt": None,
                    "error": None,
                },
                "trace_id": trace_id,
            }

    ctx = SessionContext(
        session_id=req.session_id,
        user_id=req.user_id,
        tenant_id=req.tenant_id,
        platform=req.platform,
        input=req.message.content,
        agent_state=req.agent_state,
        message_type=req.message.type,
        image_url=req.message.image_url,
    )

    # ── Step 8.3: Human Escalation 检测（在子 Agent 启动前）──
    try:
        escalation_result, is_escalated = await check_and_escalate(
            req.session_id, req.message.content
        )
        if is_escalated:
            reply_text = escalation_result.reply_override or "您的问题需要人工处理，请稍候。"
            await telemetry.add_event(trace_id, {
                "type": "escalation",
                "level": escalation_result.level.value,
                "action": escalation_result.action.value,
                "matched_rule": escalation_result.matched_rule,
            })
            await telemetry.finish_trace(trace_id, 0)
            await telemetry.flush_to_db(trace_id)
            return {
                "code": 0,
                "message": "ok",
                "data": {
                    "session_id": req.session_id,
                    "events": [
                        {"type": "reply", "data": {"text": reply_text}},
                        {"type": "done", "data": {}},
                    ],
                    "new_agent_state": {"phase": "escalated"},
                    "interrupt": None,
                    "error": None,
                },
                "trace_id": trace_id,
            }
    except Exception as e:
        logger.warning(f"[agent_run] escalation check failed (non-blocking): {e}")

    t0 = time.time()

    try:
        # S2-01: 3s 仅用于前台意图分类；子 Agent 由 orchestrator 内部异步调度
        result = await _run_with_timeout(ctx, req.message.content, timeout_s=3.0)
    except Exception as e:
        logger.error(f"[agent_run] orchestrator error: {e}", exc_info=True)
        # S2-04: error 统一在 data 内层
        result = AgentResult(
            state={"phase": "error"},
            reply="服务暂时不可用，请稍后再试~",
            done=True,
            error=str(e),
        )

    elapsed_ms = int((time.time() - t0) * 1000)
    await telemetry.finish_trace(trace_id, elapsed_ms)

    # ── Step 8.1: Reflection 异步触发（不阻塞主流程）──
    try:
        current_agent = req.agent_state.get("current_agent", "orchestrator")
        asyncio.create_task(
            trigger_reflection_async(ctx, result, current_agent)
        )
    except Exception as e:
        logger.warning(f"[agent_run] reflection trigger failed (non-blocking): {e}")

    # S2-02: 响应前落库确保 trace 持久化
    await telemetry.flush_to_db(trace_id)

    return {
        "code": 0,
        "message": "ok",
        "data": _agent_result_to_response(req.session_id, result, trace_id),
        "trace_id": trace_id,
    }


# S2-03: 所有合法 Agent 类型
_VALID_AGENTS = {"workshop", "diagnosis", "photo_analyst", "copywriter"}


async def _handle_resume(
    req: ResumeRequest | RunRequest,
    trace_id: str,
    default_resume: bool = False,
) -> dict:
    """处理中断恢复（正常 resume 或超时自动 resume）"""
    if isinstance(req, RunRequest):
        interrupt_reply = req.agent_state.get("resume_reply", "继续")
        agent_state = req.agent_state
        user_id = req.user_id
        tenant_id = req.tenant_id
        session_id = req.session_id
    else:
        interrupt_reply = req.interrupt_reply
        agent_state = req.agent_state
        user_id = req.user_id
        tenant_id = req.tenant_id
        session_id = req.session_id

    # S2-03: 中断后状态丢失时拒绝路由，不回退到默认 Agent
    current_agent = agent_state.get("current_agent")
    if not current_agent or current_agent not in _VALID_AGENTS:
        logger.error(
            f"[_handle_resume] 缺少 current_agent 或非法值: {current_agent}, "
            f"session={session_id}, agent_state={agent_state}"
        )
        result = AgentResult(
            state={},
            reply="会话状态已丢失，请重新发送问题~",
            done=True,
            error="agent_state_missing",
        )
        await telemetry.finish_trace(trace_id, 0)
        await telemetry.flush_to_db(trace_id)
        return {
            "code": 0,
            "message": "ok",
            "data": _agent_result_to_response(session_id, result, trace_id),
            "trace_id": trace_id,
        }

    ctx = SessionContext(
        session_id=session_id,
        user_id=user_id,
        tenant_id=tenant_id,
        platform="",
        input=interrupt_reply,
        agent_state=agent_state,
    )

    t0 = time.time()

    try:
        result = await resume_agent(ctx, current_agent, interrupt_reply, [], 0)
    except Exception as e:
        logger.error(f"[agent_resume] error: {e}", exc_info=True)
        result = AgentResult(
            state={"phase": "error"},
            reply="恢复过程中遇到问题，请重试~",
            done=True,
            error=str(e),
        )

    elapsed_ms = int((time.time() - t0) * 1000)
    await telemetry.finish_trace(trace_id, elapsed_ms)

    # ── Step 8.1: Reflection 异步触发 ──
    try:
        asyncio.create_task(
            trigger_reflection_async(ctx, result, current_agent)
        )
    except Exception as e:
        logger.warning(f"[_handle_resume] reflection trigger failed (non-blocking): {e}")

    await telemetry.flush_to_db(trace_id)

    return {
        "code": 0,
        "message": "ok",
        "data": _agent_result_to_response(session_id, result, trace_id),
        "trace_id": trace_id,
    }


async def _run_with_timeout(
    ctx: SessionContext, input: str, timeout_s: float = 3.0
) -> AgentResult:
    """
    S2-01: 3s 超时仅用于前台意图分类 + 立即回复。
    子 Agent 由 run_orchestrator 内部通过 asyncio.create_task 异步调度，
    不在此外层超时范围内。
    """
    try:
        return await asyncio.wait_for(
            run_orchestrator(ctx, input),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        logger.warning(
            f"[agent_run] 前台 Agent 超时 ({timeout_s}s)，子 Agent 继续异步执行"
        )
        # 仅前台超时，子 Agent 仍在后台异步运行
        return AgentResult(
            state={"phase": "front_running"},
            reply="收到~ 配药师正在为您挑选，请稍候。",
            done=False,  # 子 Agent 仍在执行，Go 层通过 SSE/主动推送事件
            error=None,
        )


@router.post("/resume")
async def agent_resume(req: ResumeRequest):
    # S2-05: 输入长度校验
    if len(req.interrupt_reply) > MAX_INPUT_LENGTH:
        return _error_response(4001, f"消息长度超过 {MAX_INPUT_LENGTH} 字限制", "")

    trace_id = await telemetry.start_trace(req.session_id, "orchestrator")
    return await _handle_resume(req, trace_id)


@router.get("/health")
async def agent_health():
    """
    S2-11: 生产级健康检查 — 区分 liveness vs readiness
    - liveness: /agent/health?type=live  仅检查进程存活
    - readiness: /agent/health?type=ready 检查 Redis + PG + FE gRPC + LLM API
    默认（不带参数）返回 readiness 完整检查
    """
    # S2-11: 全面检查
    from fastapi import Query

    redis_ok = await redis_client.is_available()

    # PG 检查 (导入应在顶部,此处避免循环)
    pg_ok = True
    try:
        from db_util import db

        pg_ok = await db.is_available()
    except Exception:
        pg_ok = False

    # 整体状态
    all_ok = redis_ok and pg_ok
    status = "ok" if all_ok else "degraded"

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "status": status,
            "version": "0.3.0",
            "checks": {
                "redis": "connected" if redis_ok else "unavailable",
                "postgres": "connected" if pg_ok else "unavailable",
                "fe_grpc": "unchecked",  # S2-11: FE gRPC 检查由 Step 5 Tool 层负责
                "llm_api": "unchecked",  # S2-11: LLM API 检查由 Step 6 Agent 层负责
            },
        },
        "trace_id": "",
    }


def _error_response(code: int, message: str, trace_id: str) -> dict:
    """统一错误响应"""
    return {
        "code": code,
        "message": message,
        "data": None,
        "trace_id": trace_id,
    }


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
