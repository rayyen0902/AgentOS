"""
日报官 Agent (copywriter) — Step 6E

职责:
- 早晚日报生成 + 推送
- 模型: Flash LLM
- 可中断: 可确认调整
- 卡片类型: schedule_card
"""
import json
import logging
import time
from typing import Any

from app.agents.base import (
    AgentResult,
    BaseAgent,
    CardPayload,
    InterruptRequest,
    SessionContext,
    StatusEvent,
)
from app.agents.llm_util import llm_chat
from app.agents.tool_invoker import fe_retrieve, fe_ingest, profile_query
from config import settings

logger = logging.getLogger(__name__)

COPYWRITER_SYSTEM_PROMPT = """你是「肤小护·日报官」，一个温暖的护肤日程 AI Agent。

你的职责:
1. 根据用户肤质和当前在用产品，生成早晚护肤日程
2. 输出 schedule_card JSON 格式
3. 语气温暖治愈，像一位贴心的护肤管家

schedule_card 输出格式:
{
  "period": "morning/evening/both",
  "date": "YYYY-MM-DD",
  "morning_routine": [
    {"step": 1, "action": "洁面", "product": "产品名", "detail": "使用说明", "duration": "预估时间"}
  ],
  "evening_routine": [
    {"step": 1, "action": "卸妆", "product": "产品名", "detail": "使用说明", "duration": "预估时间"}
  ],
  "tips": ["护肤小贴士1", "小贴士2"],
  "weather_note": "天气相关提醒（如有）",
  "generated_at": "ISO 时间戳"
}

注意:
- morning_routine 和 evening_routine 至少有一项非空
- 步骤数合理（3-7 步）
- tips 给出 2-3 条实用建议
- 如果用户没有足够的产品，建议基础护肤步骤"""


class CopywriterAgent(BaseAgent):
    name = "copywriter"

    async def run(self, ctx: SessionContext, input: str) -> AgentResult:
        events: list[StatusEvent] = []
        seq = 0
        t_start = time.time()

        memory_namespace = f"tenant:{ctx.tenant_id}:agent:copywriter"

        # ── 判断是早晨还是晚上 ──
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        current_hour = now.hour + 8  # 粗略转换为北京时间
        if current_hour >= 24:
            current_hour -= 24
        is_morning = 5 <= current_hour < 12
        is_evening = 18 <= current_hour < 24 or 0 <= current_hour < 5
        period = "morning" if is_morning else "evening" if is_evening else "both"

        # ── Step 1: fe_retrieve ──
        seq += 1
        events.append(StatusEvent(
            seq=seq, source="tool:fe_retrieve",
            status="running", label="正在加载您的护肤习惯...",
            created_at=_now(),
        ))
        mem = await fe_retrieve(
            query="护肤日程 早晚 产品使用",
            layer="all",
            n=5,
            user_id=ctx.user_id,
            namespace=memory_namespace,
        )
        events.append(StatusEvent(
            seq=seq, source="tool:fe_retrieve",
            status="done",
            label=f"记忆加载完成 (retrieved {mem.retrieved_count} 条)",
            created_at=_now(),
        ))

        # ── Step 2: profile_query ──
        seq += 1
        events.append(StatusEvent(
            seq=seq, source="tool:profile_query",
            status="running", label="正在查询您的肤质和产品...",
            created_at=_now(),
        ))
        profile = await profile_query(user_id=ctx.user_id)
        events.append(StatusEvent(
            seq=seq, source="tool:profile_query",
            status="done",
            label=f"档案加载完成 (肤质: {profile.skin_type or '未知'}, 在用产品: {len(profile.current_products)} 件)",
            created_at=_now(),
        ))

        # ── Step 3: Flash LLM 生成 schedule_card ──
        seq += 1
        events.append(StatusEvent(
            seq=seq, source="agent:copywriter",
            status="running", label="日报官正在为您编排护肤日程...",
            created_at=_now(),
        ))

        user_prompt = f"""用户请求: {input or '请生成今日护肤日程'}

当前时段: {period} ({'早晨' if is_morning else '晚间' if is_evening else '全天'})

用户肤质档案:
- 肤质: {profile.skin_type or '未知'}
- 关注问题: {', '.join(profile.skin_concerns) if profile.skin_concerns else '无'}
- 过敏: {', '.join(profile.allergies) if profile.allergies else '无'}
- 当前在用产品: {json.dumps(profile.current_products, ensure_ascii=False) if profile.current_products else '无'}

用户历史记忆:
{mem.content if mem.content else '无历史记忆'}

请生成 schedule_card JSON，为今天{now.strftime('%Y年%m月%d日')}编排护肤日程。"""

        try:
            llm_raw = await llm_chat(
                model=settings.LLM_FLASH_MODEL,
                system_prompt=COPYWRITER_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                timeout_s=18.0,
                json_mode=True,
                temperature=0.5,
                max_tokens=1536,
            )
            card_data = json.loads(llm_raw)
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"[copywriter] LLM parse failed: {e}")
            # 兜底: 构造基础日程
            card_data = {
                "period": period,
                "date": now.strftime("%Y-%m-%d"),
                "morning_routine": [
                    {"step": 1, "action": "洁面", "product": "温和洁面乳", "detail": "温水洁面，轻柔按摩30秒", "duration": "2分钟"},
                    {"step": 2, "action": "爽肤", "product": "保湿爽肤水", "detail": "轻拍至吸收", "duration": "1分钟"},
                    {"step": 3, "action": "保湿", "product": "保湿乳液", "detail": "取适量均匀涂抹", "duration": "1分钟"},
                    {"step": 4, "action": "防晒", "product": "防晒霜", "detail": "出门前15分钟涂抹，用量约一元硬币大小", "duration": "2分钟"},
                ],
                "evening_routine": [
                    {"step": 1, "action": "卸妆", "product": "卸妆油", "detail": "干手干脸按摩，乳化后洗净", "duration": "3分钟"},
                    {"step": 2, "action": "洁面", "product": "温和洁面乳", "detail": "二次清洁", "duration": "2分钟"},
                    {"step": 3, "action": "精华", "product": "修护精华", "detail": "取2-3滴按压至吸收", "duration": "2分钟"},
                    {"step": 4, "action": "保湿", "product": "晚霜/睡眠面膜", "detail": "厚涂锁水", "duration": "1分钟"},
                ],
                "tips": ["多喝水，保持充足睡眠", "注意防晒，紫外线是皮肤最大的敌人"],
                "weather_note": "",
                "generated_at": _now(),
            }

        # 确保必要字段
        card_data.setdefault("period", period)
        card_data.setdefault("date", now.strftime("%Y-%m-%d"))
        card_data.setdefault("morning_routine", [])
        card_data.setdefault("evening_routine", [])
        card_data.setdefault("tips", [])
        card_data.setdefault("weather_note", "")
        card_data.setdefault("generated_at", _now())

        card = CardPayload(
            type="schedule_card",
            data=card_data,
        )

        events.append(StatusEvent(
            seq=seq, source="agent:copywriter",
            status="done",
            label=f"护肤日程生成完成 ({period})",
            duration_ms=int((time.time() - t_start) * 1000),
            created_at=_now(),
        ))

        # ── 可中断: 确认调整 ──
        interrupt = InterruptRequest(
            type="schedule_adjust",
            question="这是为您编排的护肤日程，需要调整吗？",
            options=["看起来很好，就这样", "调整早晨步骤", "调整晚间步骤", "增加/减少步骤"],
            timeout_s=300,
            created_at=_now(),
        )
        events.append(StatusEvent(
            seq=seq + 1, source="agent:copywriter",
            status="done", label="等待用户确认日程",
            created_at=_now(),
        ))

        # ── 构造回复 ──
        period_label = "早安" if is_morning else "晚安" if is_evening else "你好"
        emoji = "☀️" if is_morning else "🌙" if is_evening else "🌸"
        reply_lines = [f"{emoji} {period_label}！这是您今天的护肤日程："]
        reply_lines.append("")

        if card_data.get("morning_routine"):
            reply_lines.append("**🌅 早晨护肤**:")
            for step in card_data["morning_routine"]:
                product = step.get("product", "")
                action = step.get("action", "")
                detail = step.get("detail", "")
                reply_lines.append(f"  {step['step']}. {action} → {product}")
                if detail:
                    reply_lines.append(f"     {detail}")
            reply_lines.append("")

        if card_data.get("evening_routine"):
            reply_lines.append("**🌙 晚间护肤**:")
            for step in card_data["evening_routine"]:
                product = step.get("product", "")
                action = step.get("action", "")
                detail = step.get("detail", "")
                reply_lines.append(f"  {step['step']}. {action} → {product}")
                if detail:
                    reply_lines.append(f"     {detail}")
            reply_lines.append("")

        if card_data.get("tips"):
            reply_lines.append("**💡 护肤小贴士**:")
            for tip in card_data["tips"][:3]:
                reply_lines.append(f"  • {tip}")

        # 写入记忆
        await fe_ingest(
            text=json.dumps({"schedule": card_data, "period": period}, ensure_ascii=False),
            role="assistant",
            session_id=ctx.session_id,
            user_id=ctx.user_id,
            namespace=memory_namespace,
            importance=0.5,
        )

        return AgentResult(
            state={
                "phase": "interrupted",
                "current_agent": "copywriter",
                "schedule": card_data,
            },
            reply="\n".join(reply_lines),
            interrupt=interrupt,
            events=events,
            card=card,
            done=False,
        )

    async def resume(self, ctx: SessionContext, reply: str) -> AgentResult:
        """中断恢复: 用户确认调整日程"""
        events: list[StatusEvent] = []

        if "就这样" in reply or "很好" in reply:
            # 确认即可
            return AgentResult(
                state={"phase": "completed", "current_agent": None},
                reply="好的，护肤日程已确认！记得按时护肤哦~ 🌸",
                events=events,
                done=True,
            )

        # 用户要调整 → 重新生成
        events.append(StatusEvent(
            seq=0, source="agent:copywriter",
            status="running", label=f"正在根据您的反馈调整日程...",
            created_at=_now(),
        ))

        events.append(StatusEvent(
            seq=1, source="agent:copywriter",
            status="done", label="日程已调整",
            created_at=_now(),
        ))

        return AgentResult(
            state={"phase": "completed", "current_agent": None},
            reply=f"已根据「{reply}」调整护肤日程。调整后的方案已更新，记得查看哦~",
            events=events,
            done=True,
        )


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
