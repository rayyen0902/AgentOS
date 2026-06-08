"""
Agent 评价体系
严格对应 Step 8 文档 8.6

评价维度:
- Accuracy: 推荐产品是否匹配肤质 → Reflection Agent + 选购率
- Conversion: 推荐→选购/下单转化 → 选购回调 + 订单数据
- Retention: 用户 7 日内回访率 → 会话日志
- Trust: 采纳率 / 追问率 → Reflection Agent 评估
"""
import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.agents.llm_util import llm_chat
from config import settings
from db_util import db

logger = logging.getLogger(__name__)


# ============================================================
# 评价数据模型
# ============================================================


@dataclass
class AgentScore:
    """单个 Agent 的四维评价分数"""
    agent_name: str
    accuracy: float = 0.0    # 0.0 - 1.0
    conversion: float = 0.0  # 0.0 - 1.0
    retention: float = 0.0   # 0.0 - 1.0
    trust: float = 0.0       # 0.0 - 1.0
    overall: float = 0.0     # 加权综合分
    sample_count: int = 0
    period_days: int = 7


@dataclass
class EvaluationReport:
    """评价报告"""
    scores: list[AgentScore] = field(default_factory=list)
    summary: str = ""
    recommendations: list[str] = field(default_factory=list)
    generated_at: str = ""


# ============================================================
# Agent 评价引擎
# ============================================================


class AgentEvaluationEngine:
    """
    Agent 评价引擎。

    四维评估:
    - Accuracy (准确度): 权重 0.35
    - Conversion (转化率): 权重 0.25
    - Retention (留存率): 权重 0.20
    - Trust (信任度): 权重 0.20
    """

    name: str = "agent_evaluation"

    # 权重配置
    WEIGHTS = {
        "accuracy": 0.35,
        "conversion": 0.25,
        "retention": 0.20,
        "trust": 0.20,
    }

    # Agent type → 显示名称映射
    AGENT_DISPLAY_NAMES = {
        "workshop": "配药师",
        "diagnosis": "问卷师",
        "photo_analyst": "识肤师",
        "copywriter": "日报官",
        "orchestrator": "编排器",
    }

    async def _calculate_accuracy(
        self, agent_name: str, period_days: int = 7
    ) -> tuple[float, int]:
        """
        计算 Accuracy（准确度）。
        数据来源: Reflection Agent satisfaction。

        算法: high_satisfaction / total_reflections (按 agent_name 过滤 event_data JSON 中的 agent_name 字段)

        S8-03 修复: 使用 event_data->>'agent_name' 按 agent_name 过滤
        """
        rows = await db.fetch(
            """
            SELECT event_data
            FROM agent_audit_log
            WHERE agent_name = 'reflection'
              AND event_type = 'reflection_complete'
              AND created_at >= NOW() - make_interval(days => $1)
              AND event_data IS NOT NULL
              AND event_data->>'agent_name' = $2
            """,
            period_days, agent_name,
        )

        high = medium = low = 0
        for row in rows:
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
        if total == 0:
            return 0.0, 0

        # 加权: high=1.0, medium=0.5, low=0.0
        accuracy = (high * 1.0 + medium * 0.5) / total
        return round(accuracy, 3), total

    async def _calculate_conversion(
        self, agent_name: str, period_days: int = 7
    ) -> tuple[float, int]:
        """
        计算 Conversion（转化率）。
        数据来源: 选购回调 + 订单数据。

        S8-04 修复: event_data->>'agent_name' 按 agent_name 过滤
        """
        # 该 agent 的 workshop_card 推送次数（event_data 中包含 agent_name 字段）
        workshop_row = await db.fetchrow(
            """
            SELECT COUNT(*) AS cnt
            FROM agent_audit_log
            WHERE agent_name = 'reflection'
              AND event_type = 'reflection_complete'
              AND created_at >= NOW() - make_interval(days => $1)
              AND event_data->>'agent_name' = $2
            """,
            period_days, agent_name,
        )
        total_rec = workshop_row["cnt"] if workshop_row else 0

        # 选购事件（同 session 内的 purchase 事件）
        purchase_row = await db.fetchrow(
            """
            SELECT COUNT(*) AS cnt
            FROM agent_audit_log
            WHERE event_type IN ('purchase', 'order_placed', 'add_to_cart')
              AND created_at >= NOW() - make_interval(days => $1)
            """,
            period_days,
        )
        purchases = purchase_row["cnt"] if purchase_row else 0

        if total_rec == 0:
            return 0.0, 0

        conversion = purchases / total_rec
        return min(round(conversion, 3), 1.0), total_rec

    async def _calculate_retention(
        self, agent_name: str, period_days: int = 7
    ) -> tuple[float, int]:
        """
        计算 Retention（留存率）。
        数据来源: 会话日志 — 7 日内有 ≥ 2 次会话的用户比例。

        S8-05 修复: 通过 session_states.current_agent 过滤对应 agent 用户群
        """
        # 该 agent 服务过的用户总数
        total_row = await db.fetchrow(
            """
            SELECT COUNT(DISTINCT user_id) AS cnt
            FROM session_states
            WHERE current_agent = $1
              AND created_at >= NOW() - make_interval(days => $2)
            """,
            agent_name, period_days,
        )
        total_users = total_row["cnt"] if total_row else 0
        if total_users == 0:
            return 0.0, 0

        # 回访用户数（≥ 2 次同 agent 会话）
        retained_row = await db.fetchrow(
            """
            SELECT COUNT(*) AS cnt FROM (
                SELECT user_id
                FROM session_states
                WHERE current_agent = $1
                  AND created_at >= NOW() - make_interval(days => $2)
                GROUP BY user_id
                HAVING COUNT(*) >= 2
            ) sub
            """,
            agent_name, period_days,
        )
        retained = retained_row["cnt"] if retained_row else 0

        retention = retained / total_users
        return round(retention, 3), total_users

    async def _calculate_trust(
        self, agent_name: str, period_days: int = 7
    ) -> tuple[float, int]:
        """
        计算 Trust（信任度）。
        数据来源: Reflection Agent 评估 — 采纳率 / 追问率。

        算法: 1 - (追问次数 / 推荐次数)

        S8-06 修复: event_data->>'agent_name' 按 agent_name 过滤
        """
        # 该 agent 的 Reflection 总数
        total_row = await db.fetchrow(
            """
            SELECT COUNT(*) AS cnt
            FROM agent_audit_log
            WHERE event_type = 'reflection_complete'
              AND agent_name = 'reflection'
              AND created_at >= NOW() - make_interval(days => $1)
              AND event_data->>'agent_name' = $2
            """,
            period_days, agent_name,
        )
        total = total_row["cnt"] if total_row else 0
        if total == 0:
            return 0.0, 0

        # low satisfaction（追问/不满意）次数
        low_rows = await db.fetch(
            """
            SELECT event_data
            FROM agent_audit_log
            WHERE event_type = 'reflection_complete'
              AND agent_name = 'reflection'
              AND created_at >= NOW() - make_interval(days => $1)
              AND event_data->>'agent_name' = $2
              AND event_data IS NOT NULL
            """,
            period_days, agent_name,
        )

        low_count = 0
        for row in low_rows:
            try:
                data = json.loads(row["event_data"]) if isinstance(row["event_data"], str) else row["event_data"]
                if data.get("satisfaction") == "low":
                    low_count += 1
            except (json.JSONDecodeError, TypeError):
                continue

        trust = 1.0 - (low_count / total)
        return round(max(trust, 0.0), 3), total

    async def evaluate_agent(
        self, agent_name: str, period_days: int = 7
    ) -> AgentScore:
        """
        评估单个 Agent 的四维分数。
        """
        accuracy, acc_n = await self._calculate_accuracy(agent_name, period_days)
        conversion, conv_n = await self._calculate_conversion(agent_name, period_days)
        retention, ret_n = await self._calculate_retention(agent_name, period_days)
        trust, trust_n = await self._calculate_trust(agent_name, period_days)

        # 加权综合分
        overall = (
            accuracy * self.WEIGHTS["accuracy"]
            + conversion * self.WEIGHTS["conversion"]
            + retention * self.WEIGHTS["retention"]
            + trust * self.WEIGHTS["trust"]
        )

        sample_count = max(acc_n, conv_n, ret_n, trust_n)

        return AgentScore(
            agent_name=agent_name,
            accuracy=accuracy,
            conversion=conversion,
            retention=retention,
            trust=trust,
            overall=round(overall, 3),
            sample_count=sample_count,
            period_days=period_days,
        )

    async def evaluate_all(
        self, period_days: int = 7
    ) -> list[AgentScore]:
        """
        评估所有 Agent 类型。
        """
        agent_types = ["workshop", "diagnosis", "photo_analyst", "copywriter", "orchestrator"]

        scores = []
        for at in agent_types:
            try:
                score = await self.evaluate_agent(at, period_days)
                scores.append(score)
            except Exception as e:
                logger.error(f"[AgentEvaluation] failed to evaluate {at}: {e}")
                scores.append(AgentScore(agent_name=at))

        return scores

    async def generate_report(
        self, period_days: int = 7
    ) -> EvaluationReport:
        """
        生成完整的 Agent 评价报告。
        """
        scores = await self.evaluate_all(period_days)

        # 按综合分排序
        scores.sort(key=lambda s: s.overall, reverse=True)

        # 生成摘要
        if not scores:
            summary = "评价期内无数据。"
        else:
            best = scores[0]
            worst = scores[-1]
            avg_overall = sum(s.overall for s in scores) / max(len(scores), 1)
            summary = (
                f"评价期 {period_days} 天。"
                f"最佳 Agent: {best.agent_name} (综合分 {best.overall:.2f})。"
                f"待改进: {worst.agent_name} (综合分 {worst.overall:.2f})。"
                f"平均综合分: {avg_overall:.2f}。"
            )

        # 生成建议
        recommendations = []
        for s in scores:
            if s.overall < 0.5 and s.sample_count > 0:
                recommendations.append(
                    f"{s.agent_name}: 综合分 {s.overall:.2f} 偏低，"
                    f"Accuracy={s.accuracy:.2f} Conversion={s.conversion:.2f} "
                    f"Retention={s.retention:.2f} Trust={s.trust:.2f} "
                    f"建议检查 prompt 和知识库配置。"
                )

        from datetime import datetime, timezone
        return EvaluationReport(
            scores=scores,
            summary=summary,
            recommendations=recommendations,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    async def generate_and_persist(
        self, period_days: int = 7
    ) -> EvaluationReport:
        """
        生成评价报告并写入 agent_audit_log。
        """
        report = await self.generate_report(period_days)

        try:
            await db.execute(
                """
                INSERT INTO agent_audit_log (session_id, agent_name, event_type, event_data)
                VALUES ($1, $2, $3, $4)
                """,
                "evaluation:periodic",
                "agent_evaluation",
                "evaluation_report",
                json.dumps({
                    "scores": [
                        {
                            "agent_name": s.agent_name,
                            "accuracy": s.accuracy,
                            "conversion": s.conversion,
                            "retention": s.retention,
                            "trust": s.trust,
                            "overall": s.overall,
                            "sample_count": s.sample_count,
                        }
                        for s in report.scores
                    ],
                    "summary": report.summary,
                    "recommendations": report.recommendations,
                    "period_days": period_days,
                    "generated_at": report.generated_at,
                }, ensure_ascii=False),
            )

            logger.info(
                f"[AgentEvaluation] report persisted: {report.summary[:120]}"
            )
        except Exception as e:
            logger.error(f"[AgentEvaluation] failed to persist report: {e}")

        return report


# ============================================================
# 便捷函数
# ============================================================


async def run_evaluation(period_days: int = 7) -> dict[str, Any]:
    """
    运行 Agent 评价并返回结果。

    用法（Cron 定时任务或手动调用）:
        result = await run_evaluation()
    """
    engine = AgentEvaluationEngine()
    report = await engine.generate_and_persist(period_days)

    return {
        "scores": [
            {
                "agent_name": s.agent_name,
                "accuracy": s.accuracy,
                "conversion": s.conversion,
                "retention": s.retention,
                "trust": s.trust,
                "overall": s.overall,
                "sample_count": s.sample_count,
            }
            for s in report.scores
        ],
        "summary": report.summary,
        "recommendations": report.recommendations,
        "weights": AgentEvaluationEngine.WEIGHTS,
    }


# 全局单例
evaluation_engine = AgentEvaluationEngine()
