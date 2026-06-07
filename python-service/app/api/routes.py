"""
API 路由 — /agent/run, /agent/resume, /agent/health
Step 6 实现: 使用真实 Orchestrator 意图分类 + 委派
"""
import time
import uuid
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.agents.base import SessionContext, AgentResult
from app.agents.orchestrator import run_orchestrator, resume_agent
from app.agents.interrupt_handler import (
    check_interrupt_timeout,
    check_diagnosis_step_timeout,
    check_diagnosis_quit,
)
from app.observation.telemetry import telemetry
from redis_util import redis_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agent")


class MessageInput(BaseModel):
    type: str = "text"
    content: str = ""
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
    interrupt_reply: str
    agent_state: dict = {}


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

    # reply event
    events.append({
        "type": "reply",
        "data": {"text": result.reply},
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

    return {
        "session_id": session_id,
        "events": events,
        "new_agent_state": result.state,
        "interrupt": interrupt,
        "error": result.error,
    }


@router.post("/run")
async def agent_run(req: RunRequest):
    trace_id = await telemetry.start_trace(req.session_id, "orchestrator")

    # ── 6.6: 中断超时检测 ──
    agent_state = dict(req.agent_state)
    timeout_resume = check_interrupt_timeout(agent_state)
    if timeout_resume:
        logger.info(
            f"[agent_run] 中断超时，自动使用默认答案继续, "
            f"session={req.session_id}, agent={agent_state.get('current_agent')}"
        )
        # 使用自动生成的兜底回复继续子 Agent
        agent_state.update(timeout_resume)
        req.agent_state = agent_state
        # 转入 resume 流程
        return await _handle_resume(req, trace_id, default_resume=True)

    # ── 6.6: 问卷单步超时检测 ──
    step_timeout = check_diagnosis_step_timeout(agent_state)
    if step_timeout:
        logger.info(
            f"[agent_run] 问卷单步超时, 重发当前问题, "
            f"session={req.session_id}, step={step_timeout.get('diagnosis_step')}"
        )
        # 重置 step_started_at 并在 agent_state 上标记重发
        req.agent_state = {**agent_state, **step_timeout}
        # 允许继续进入 orchestrator（它将重发当前步骤的问题）
        from app.agents.diagnosis_agent import DIAGNOSIS_STEPS
        step_idx = step_timeout.get("diagnosis_step", 1) - 1
        if 0 <= step_idx < len(DIAGNOSIS_STEPS):
            step_info = DIAGNOSIS_STEPS[step_idx]
            options_text = "\n".join(
                f"{chr(65 + i)}. {opt}" for i, opt in enumerate(step_info["options"])
            )
            question_text = f"⏰ 上一问已超时，重新发送:\n\n{step_info['question']}\n\n{options_text}"
            return {
                "code": 0,
                "message": "ok",
                "data": {
                    "session_id": req.session_id,
                    "events": [
                        {"type": "status", "data": {"seq": 0, "source": "agent:diagnosis", "status": "running", "label": f"单步超时,重发第{step_idx + 1}/7步"}},
                        {"type": "reply", "data": {"text": question_text}},
                    ],
                    "new_agent_state": req.agent_state,
                    "interrupt": None,
                    "error": None,
                },
                "trace_id": trace_id,
            }

    # ── 6.6: 问卷中途退出检测 ──
    if check_diagnosis_quit(req.message.content, agent_state):
        logger.info(f"[agent_run] 问卷中途退出, session={req.session_id}")
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "session_id": req.session_id,
                "events": [
                    {"type": "status", "data": {"seq": 0, "source": "agent:diagnosis", "status": "done", "label": "用户退出问卷"}},
                    {"type": "reply", "data": {"text": "已退出肤质问诊。有任何护肤问题随时找我哦~"}},
                    {"type": "done", "data": {}},
                ],
                "new_agent_state": {},  # 清空 agent_state (6.6)
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

    t0 = time.time()

    try:
        # 外层 3s 超时（前台 Agent 总体超时）
        result = await _run_with_timeout(ctx, req.message.content, timeout_s=3.0)
    except Exception as e:
        logger.error(f"[agent_run] orchestrator error: {e}", exc_info=True)
        result = AgentResult(
            state={"phase": "error"},
            reply="服务暂时不可用，请稍后再试~",
            done=True,
            error=str(e),
        )

    elapsed_ms = int((time.time() - t0) * 1000)
    await telemetry.finish_trace(trace_id, elapsed_ms)

    return {
        "code": 0,
        "message": "ok",
        "data": _agent_result_to_response(req.session_id, result, trace_id),
        "trace_id": trace_id,
    }


async def _handle_resume(req: ResumeRequest | RunRequest, trace_id: str, default_resume: bool = False) -> dict:
    """处理中断恢复（正常 resume 或超时自动 resume）"""
    if isinstance(req, RunRequest):
        # 从 RunRequest 构造 ResumeRequest-like 行为
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

    current_agent = agent_state.get("current_agent", "workshop")

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

    return {
        "code": 0,
        "message": "ok",
        "data": _agent_result_to_response(session_id, result, trace_id),
        "trace_id": trace_id,
    }


async def _run_with_timeout(
    ctx: SessionContext, input: str, timeout_s: float = 3.0
) -> AgentResult:
    """外覆 asyncio.wait_for 确保前台 Agent 整体 3s 超时"""
    import asyncio
    try:
        return await asyncio.wait_for(
            run_orchestrator(ctx, input),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        logger.warning(f"[agent_run] 前台 Agent 总体超时 ({timeout_s}s)")
        return AgentResult(
            state={"phase": "error"},
            reply="稍后再试~",
            done=True,
            error="frontend_timeout",
        )


@router.post("/resume")
async def agent_resume(req: ResumeRequest):
    trace_id = await telemetry.start_trace(req.session_id, "orchestrator")
    return await _handle_resume(req, trace_id)


@router.get("/health")
async def agent_health():
    redis_ok = await redis_client.is_available()
    return {
        "code": 0,
        "message": "ok",
        "data": {"status": "ok" if redis_ok else "degraded", "version": "0.3.0"},
        "trace_id": "",
    }


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
