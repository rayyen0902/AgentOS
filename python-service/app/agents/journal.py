"""
Agent Journal（成长日志）定时任务
严格对应 Step 8 文档 8.4

触发: 每周日 00:00 UTC 定时任务（Cron）
内容:
- 本周服务用户数 / 推荐次数
- 采纳率（选购/下单）
- 高频需求 Top3
- 新发现（Reflection 汇总）
- 策略调整建议

输出: 写入 agent_audit_log + 通知管理员
"""
import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from app.agents.llm_util import llm_chat
from config import settings
from db_util import db

logger = logging.getLogger(__name__)


# ============================================================
# Journal 数据模型
# ============================================================


class AgentJournal:
    """
    Agent Journal 生成器。

    每周日 00:00 UTC 生成一份包含以下内容的日志:
    1. 本周服务用户数 / 推荐次数
    2. 采纳率（选购/下单）
    3. 高频需求 Top3
    4. 新发现（Reflection 汇总）
    5. 策略调整建议
    """

    name: str = "agent_journal"

    JOURNAL_SYSTEM_PROMPT = """你是一个护肤品 AI Agent 系统的运营分析专家。
你的任务是根据本周的数据统计，生成一份 Agent Journal（成长日志）。

请严格按以下 JSON 格式输出：
{
  "summary": "本周运营概况（2-3 句话）",
  "highlights": ["亮点1", "亮点2"],
  "concerns": ["关注点1", "关注点2"],
  "suggestions": [
    {
      "category": "agent_behavior|product_planning|user_experience|risk_control",
      "priority": "high|medium|low",
      "suggestion": "具体建议",
      "rationale": "理由"
    }
  ],
  "action_items": ["具体行动项1", "具体行动项2"]
}"""

    def _get_week_range(self) -> tuple[datetime, datetime]:
        """
        计算本周范围：最近一个周日 00:00 UTC 到当前时间。

        S8-07 修复: 周日触发时，days_since_sunday=0 → 改为 7，回退到上周日，
        确保窗口覆盖完整的上周一~周日。
        """
        now = datetime.now(timezone.utc)
        # Monday=0, Sunday=6
        # Monday: +1=1 (回退1天=周日), ... Saturday: +1=7→0 (回退0天), Sunday: 6+1=7→0 (回退0天=今天)
        # 修正: Sunday 时 days_since_sunday=0，应改为 7 回退到上周日
        if now.weekday() == 6:
            days_since_sunday = 7  # Sunday → 回退到上周日
        else:
            days_since_sunday = now.weekday() + 1  # Mon=1, Tue=2, ..., Sat=6
        last_sunday = now - timedelta(days=days_since_sunday)
        week_start = last_sunday.replace(hour=0, minute=0, second=0, microsecond=0)
        return week_start, now

    async def _query_service_stats(
        self, week_start: datetime, week_end: datetime
    ) -> dict[str, Any]:
        """
        查询本周服务统计数据。
        """
        # 服务用户数（去重 user_id）
        user_count_row = await db.fetchrow(
            """
            SELECT COUNT(DISTINCT user_id) AS cnt
            FROM session_states
            WHERE created_at >= $1 AND created_at <= $2
            """,
            week_start, week_end,
        )
        user_count = user_count_row["cnt"] if user_count_row else 0

        # 总会话数
        session_count_row = await db.fetchrow(
            """
            SELECT COUNT(*) AS cnt
            FROM session_states
            WHERE created_at >= $1 AND created_at <= $2
            """,
            week_start, week_end,
        )
        session_count = session_count_row["cnt"] if session_count_row else 0

        # 推荐次数（workshop_card 推送次数）
        rec_count_row = await db.fetchrow(
            """
            SELECT COUNT(*) AS cnt
            FROM agent_audit_log
            WHERE agent_name = 'reflection'
              AND event_type = 'reflection_complete'
              AND created_at >= $1 AND created_at <= $2
            """,
            week_start, week_end,
        )
        rec_count = rec_count_row["cnt"] if rec_count_row else 0

        return {
            "user_count": user_count,
            "session_count": session_count,
            "recommendation_count": rec_count,
        }

    async def _query_adoption_rate(
        self, week_start: datetime, week_end: datetime
    ) -> dict[str, Any]:
        """
        查询采纳率数据。
        """
        # 从 audit_log 中统计满意度分布
        satisfaction_rows = await db.fetch(
            """
            SELECT event_data
            FROM agent_audit_log
            WHERE agent_name = 'reflection'
              AND event_type = 'reflection_complete'
              AND created_at >= $1 AND created_at <= $2
              AND event_data IS NOT NULL
            """,
            week_start, week_end,
        )

        high = medium = low = 0
        for row in satisfaction_rows:
            try:
                data = json.loads(row["event_data"]) if isinstance(row["event_data"], str) else row["event_data"]
                sat = data.get("satisfaction", "medium")
                if sat == "high":
                    high += 1
                elif sat == "low":
                    low += 1
                else:
                    medium += 1
            except (json.JSONDecodeError, TypeError):
                continue

        total = high + medium + low
        adoption = high / max(total, 1)

        return {
            "satisfaction_high": high,
            "satisfaction_medium": medium,
            "satisfaction_low": low,
            "adoption_rate": round(adoption, 3),
        }

    async def _query_top_demands(
        self, week_start: datetime, week_end: datetime
    ) -> list[dict]:
        """
        查询高频需求 Top3（从 Reflection 汇总中提取）。
        """
        rows = await db.fetch(
            """
            SELECT event_data
            FROM agent_audit_log
            WHERE agent_name = 'reflection'
              AND event_type = 'reflection_complete'
              AND created_at >= $1 AND created_at <= $2
              AND event_data IS NOT NULL
            """,
            week_start, week_end,
        )

        from collections import Counter
        lessons_counter: Counter = Counter()

        for row in rows:
            try:
                data = json.loads(row["event_data"]) if isinstance(row["event_data"], str) else row["event_data"]
                lesson = data.get("lesson", "")
                if lesson and lesson not in ("", "null", "None"):
                    lessons_counter[lesson] += 1
            except (json.JSONDecodeError, TypeError):
                continue

        top3 = lessons_counter.most_common(3)
        return [
            {"text": text, "frequency": freq}
            for text, freq in top3
        ]

    async def _query_reflection_insights(
        self, week_start: datetime, week_end: datetime
    ) -> list[str]:
        """
        汇总本周 Reflection 的新发现（rule_candidate）。
        """
        rows = await db.fetch(
            """
            SELECT event_data
            FROM agent_audit_log
            WHERE agent_name = 'reflection'
              AND event_type = 'reflection_complete'
              AND created_at >= $1 AND created_at <= $2
              AND event_data IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 50
            """,
            week_start, week_end,
        )

        insights: list[str] = []
        for row in rows:
            try:
                data = json.loads(row["event_data"]) if isinstance(row["event_data"], str) else row["event_data"]
                rule = data.get("rule_candidate", "")
                if rule and rule not in ("", "null", "None"):
                    if rule not in insights:
                        insights.append(rule)
            except (json.JSONDecodeError, TypeError):
                continue

        return insights

    async def _query_escalation_stats(
        self, week_start: datetime, week_end: datetime
    ) -> dict[str, Any]:
        """
        查询升级事件统计。
        """
        rows = await db.fetch(
            """
            SELECT event_data
            FROM agent_audit_log
            WHERE agent_name = 'human_escalation'
              AND event_type = 'escalation_triggered'
              AND created_at >= $1 AND created_at <= $2
              AND event_data IS NOT NULL
            """,
            week_start, week_end,
        )

        level_counts = {"emergency": 0, "urgent": 0, "high": 0, "medium": 0}
        for row in rows:
            try:
                data = json.loads(row["event_data"]) if isinstance(row["event_data"], str) else row["event_data"]
                level = data.get("level", "")
                if level in level_counts:
                    level_counts[level] += 1
            except (json.JSONDecodeError, TypeError):
                continue

        return {
            "escalation_total": sum(level_counts.values()),
            "escalation_by_level": level_counts,
        }

    async def generate(self) -> dict[str, Any]:
        """
        生成本周 Agent Journal。

        Returns:
            Journal 数据 dict
        """
        week_start, week_end = self._get_week_range()
        logger.info(
            f"[AgentJournal] generating for week {week_start.date()} → {week_end.date()}"
        )

        # 并发查询所有统计数据
        service_stats, adoption, top_demands, insights, escalation = await asyncio.gather(
            self._query_service_stats(week_start, week_end),
            self._query_adoption_rate(week_start, week_end),
            self._query_top_demands(week_start, week_end),
            self._query_reflection_insights(week_start, week_end),
            self._query_escalation_stats(week_start, week_end),
        )

        # 构建 LLM 分析 prompt
        data_summary = json.dumps({
            "period": f"{week_start.date()} → {week_end.date()}",
            "service": service_stats,
            "adoption": adoption,
            "top_demands": top_demands,
            "insights": insights,
            "escalation": escalation,
        }, ensure_ascii=False, indent=2)

        user_prompt = f"""请根据以下本周数据生成 Agent Journal：

{data_summary}

要求：
1. summary 简洁有力，突出关键数据
2. suggestions 要具体可行，每项建议附带理由
3. action_items 要是可执行的具体行动"""

        try:
            response = await llm_chat(
                model=settings.LLM_PRO_MODEL,
                system_prompt=self.JOURNAL_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                timeout_s=30.0,
                json_mode=True,
                temperature=0.5,
                max_tokens=2048,
            )
            journal = json.loads(response)

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"[AgentJournal] LLM output parse error: {e}")
            journal = {
                "summary": f"本周服务 {service_stats['user_count']} 位用户，共 {service_stats['session_count']} 次会话。",
                "highlights": [],
                "concerns": [],
                "suggestions": [],
                "action_items": [],
            }

        # 合并原始数据
        journal["_meta"] = {
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "service_stats": service_stats,
            "adoption": adoption,
            "top_demands": top_demands,
            "insights_count": len(insights),
            "escalation": escalation,
        }

        return journal

    async def generate_and_persist(self) -> dict[str, Any]:
        """
        生成 Journal 并写入 agent_audit_log。

        Returns:
            Journal 数据 dict
        """
        try:
            journal = await self.generate()

            # 写入 agent_audit_log
            await db.execute(
                """
                INSERT INTO agent_audit_log (session_id, agent_name, event_type, event_data)
                VALUES ($1, $2, $3, $4)
                """,
                "journal:weekly",
                "agent_journal",
                "journal_generated",
                json.dumps(journal, ensure_ascii=False),
            )

            logger.info(
                f"[AgentJournal] persisted: week={journal.get('_meta', {}).get('week_start', '?')} "
                f"summary={journal.get('summary', '')[:80]}"
            )

            return journal

        except Exception as e:
            logger.error(f"[AgentJournal] generate_and_persist failed: {e}")
            raise


# ============================================================
# Cron 任务入口
# ============================================================


async def run_weekly_journal() -> dict[str, Any]:
    """
    每周日 00:00 UTC 由 Cron 触发的入口函数。

    用法（在定时任务调度器中）:
        result = await run_weekly_journal()
    """
    journal = AgentJournal()

    try:
        result = await journal.generate_and_persist()

        # 通知管理员（打印日志，实际可对接 webhook/企业微信/钉钉）
        summary = result.get("summary", "Agent Journal 已生成")
        suggestions = result.get("suggestions", [])
        logger.info(
            f"[AgentJournal] === WEEKLY JOURNAL ===\n"
            f"SUMMARY: {summary}\n"
            f"SUGGESTIONS: {len(suggestions)} items\n"
        )

        return result

    except Exception as e:
        logger.error(f"[AgentJournal] weekly journal failed: {e}")
        return {"error": str(e)}


# 全局单例
agent_journal = AgentJournal()
