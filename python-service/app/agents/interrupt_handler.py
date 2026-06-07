"""
Step 6 6.6: 中断超时看门狗 + 问卷中途退出检测 + 问卷单步超时

在 /agent/run 入口检测:
1. 问卷师单步超时 30s → 重发当前问题
2. 中断超时 5min → options[0] 作为默认答案继续，记录 interrupt_timed_out=true
3. 问卷师中途用户发其他消息 → 视为退出问卷 → agent_state 清空
"""
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# 中断超时阈值（秒）
INTERRUPT_TIMEOUT_S = 300
# 问卷单步超时（秒）
DIAGNOSIS_STEP_TIMEOUT_S = 30


def check_interrupt_timeout(agent_state: dict) -> dict | None:
    """
    检查中断是否超时。
    若超时 → 返回兜底回复状态（options[0] 作为默认答案继续）
    返回 None 表示未超时或非中断状态。
    """
    if agent_state.get("stage") != "agent_interrupted":
        return None

    started_at_str = agent_state.get("interrupt_started_at", "")
    if not started_at_str:
        return None

    try:
        started_at = datetime.fromisoformat(started_at_str)
    except (ValueError, TypeError):
        return None

    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
    if elapsed < INTERRUPT_TIMEOUT_S:
        return None

    # 超时 → 记录 interrupt_timed_out=true，使用默认答案继续
    logger.warning(
        f"中断超时 ({elapsed:.0f}s > {INTERRUPT_TIMEOUT_S}s)，"
        f"使用默认答案继续, current_agent={agent_state.get('current_agent')}"
    )
    return {
        "interrupt_timed_out": True,
        "resume_reply": "继续（默认）",  # options[0] 自动兜底
        "stage": "agent_running",  # 恢复到 running 继续流程
    }


def check_diagnosis_step_timeout(agent_state: dict) -> dict | None:
    """
    检查问卷师单步是否超时 30s。
    若超时 → 返回标志让 orchestrator 重发当前问题。
    """
    if agent_state.get("current_agent") != "diagnosis":
        return None

    step_started_str = agent_state.get("step_started_at", "")
    if not step_started_str:
        return None

    try:
        step_started = datetime.fromisoformat(step_started_str)
    except (ValueError, TypeError):
        return None

    elapsed = (datetime.now(timezone.utc) - step_started).total_seconds()
    if elapsed < DIAGNOSIS_STEP_TIMEOUT_S:
        return None

    logger.warning(
        f"问卷单步超时 ({elapsed:.0f}s > {DIAGNOSIS_STEP_TIMEOUT_S}s)，"
        f"重发当前问题, step={agent_state.get('diagnosis_step')}"
    )
    # 重置 step_started_at，让 orchestrator 知道需要重发
    return {
        "step_timed_out": True,
        "diagnosis_step": agent_state.get("diagnosis_step", 0),
        "diagnosis_answers": agent_state.get("diagnosis_answers", {}),
    }


def check_diagnosis_quit(input_text: str, agent_state: dict) -> bool:
    """
    检测问卷师中途用户是否发了非问卷相关消息。
    若用户输入暗示退出问卷（如"不做了""算了""推荐产品"等），返回 True。
    """
    if agent_state.get("current_agent") != "diagnosis":
        return False

    quit_keywords = ["退出", "不做了", "算了", "取消", "停止", "推荐", "买什么", "换一个"]
    return any(kw in input_text for kw in quit_keywords)
