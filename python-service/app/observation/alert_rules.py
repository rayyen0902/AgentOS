"""
Observation Layer 告警规则
严格对应 Step 8 文档 8.5

告警规则:
- 任意 Tool 失败率 > 10% / 5min → WARNING — 站内通知
- Agent 整体失败率 > 5% / 5min → ERROR — 站内 + 短信
- LLM p95 延迟 > 8s → WARNING — 站内通知
- FE gRPC 错误率 > 20% / 5min → CRITICAL — 站内 + 短信 + 自动降级（无记忆模式）
"""
import asyncio
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from db_util import db

logger = logging.getLogger(__name__)


# ============================================================
# 告警级别
# ============================================================


class AlertLevel(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class AlertRule:
    """单条告警规则"""
    metric: str          # 指标名称
    threshold: float     # 阈值
    window_minutes: int  # 时间窗口（分钟）
    level: AlertLevel
    action: str          # 动作描述
    comparator: str = ">"  # > | < | >=


@dataclass
class AlertEvent:
    """告警事件"""
    rule: AlertRule
    current_value: float
    message: str
    triggered_at: float = field(default_factory=time.time)


# ============================================================
# 告警规则定义（严格对应 Step 8 文档 8.5）
# ============================================================


ALERT_RULES: list[AlertRule] = [
    AlertRule(
        metric="tool_failure_rate",
        threshold=0.10,       # > 10%
        window_minutes=5,
        level=AlertLevel.WARNING,
        action="站内通知",
    ),
    AlertRule(
        metric="agent_failure_rate",
        threshold=0.05,       # > 5%
        window_minutes=5,
        level=AlertLevel.ERROR,
        action="站内 + 短信",
    ),
    AlertRule(
        metric="llm_p95_latency_s",
        threshold=8.0,        # > 8s
        window_minutes=5,
        level=AlertLevel.WARNING,
        action="站内通知",
    ),
    AlertRule(
        metric="fe_grpc_error_rate",
        threshold=0.20,       # > 20%
        window_minutes=5,
        level=AlertLevel.CRITICAL,
        action="站内 + 短信 + 自动降级（无记忆模式）",
    ),
]


# ============================================================
# Observation 告警引擎
# ============================================================


class ObservationAlertEngine:
    """
    Observation 告警引擎。

    指标计算:
    - tool_failure_rate: 从 observation_traces 中统计 tool 失败事件 / 总 tool 调用
    - agent_failure_rate: 从 agent_audit_log 中统计 agent error 事件 / 总事件
    - llm_p95_latency_s: 从 observation_traces 中计算 LLM 延迟 p95
    - fe_grpc_error_rate: 从 agent_audit_log 中统计 fe_ingest/fe_retrieve 失败 / 总调用
    """

    name: str = "observation_alert"

    def __init__(self):
        self._last_alert: dict[str, float] = {}  # rule metric → last alert timestamp

    def _should_throttle(self, metric: str, cooldown_s: int = 300) -> bool:
        """
        告警节流：同一指标 5 分钟内不重复告警。
        """
        last = self._last_alert.get(metric, 0)
        if time.time() - last < cooldown_s:
            return True
        return False

    def _mark_alerted(self, metric: str) -> None:
        """
        记录告警时间。
        """
        self._last_alert[metric] = time.time()

    async def _calculate_tool_failure_rate(
        self, window_minutes: int = 5
    ) -> tuple[float, int, int]:
        """
        计算 Tool 失败率（最近 N 分钟）。

        Returns:
            (failure_rate, total_calls, failed_calls)
        """
        rows = await db.fetch(
            """
            SELECT events
            FROM observation_traces
            WHERE created_at >= NOW() - ($1 || ' minutes')::INTERVAL
            """,
            str(window_minutes),
        )

        total = 0
        failed = 0
        for row in rows:
            events = row["events"] if isinstance(row["events"], list) else json.loads(row["events"] or "[]")
            for evt in events:
                if evt.get("type") == "tool_call":
                    total += 1
                    if evt.get("status") == "error":
                        failed += 1

        rate = failed / max(total, 1)
        return rate, total, failed

    async def _calculate_agent_failure_rate(
        self, window_minutes: int = 5
    ) -> tuple[float, int, int]:
        """
        计算 Agent 整体失败率（最近 N 分钟）。
        """
        total_row = await db.fetchrow(
            """
            SELECT COUNT(*) AS cnt
            FROM agent_audit_log
            WHERE created_at >= NOW() - ($1 || ' minutes')::INTERVAL
            """,
            str(window_minutes),
        )
        total = total_row["cnt"] if total_row else 0

        failed_row = await db.fetchrow(
            """
            SELECT COUNT(*) AS cnt
            FROM agent_audit_log
            WHERE created_at >= NOW() - ($1 || ' minutes')::INTERVAL
              AND event_type IN ('agent_error', 'agent_timeout', 'run_failed')
            """,
            str(window_minutes),
        )
        failed = failed_row["cnt"] if failed_row else 0

        rate = failed / max(total, 1)
        return rate, total, failed

    async def _calculate_llm_p95_latency(
        self, window_minutes: int = 5
    ) -> tuple[float, list[float]]:
        """
        计算 LLM p95 延迟（最近 N 分钟）。

        Returns:
            (p95_latency_s, all_latencies)
        """
        rows = await db.fetch(
            """
            SELECT events
            FROM observation_traces
            WHERE created_at >= NOW() - ($1 || ' minutes')::INTERVAL
            """,
            str(window_minutes),
        )

        latencies: list[float] = []
        for row in rows:
            events = row["events"] if isinstance(row["events"], list) else json.loads(row["events"] or "[]")
            for evt in events:
                if evt.get("type") == "llm_call":
                    latency_s = evt.get("duration_ms", 0) / 1000.0
                    if latency_s > 0:
                        latencies.append(latency_s)

        if not latencies:
            return 0.0, []

        latencies.sort()
        p95_idx = int(len(latencies) * 0.95)
        p95 = latencies[min(p95_idx, len(latencies) - 1)]

        return p95, latencies

    async def _calculate_fe_grpc_error_rate(
        self, window_minutes: int = 5
    ) -> tuple[float, int, int]:
        """
        计算 FE gRPC 错误率（最近 N 分钟）。
        """
        rows = await db.fetch(
            """
            SELECT events
            FROM observation_traces
            WHERE created_at >= NOW() - ($1 || ' minutes')::INTERVAL
            """,
            str(window_minutes),
        )

        total = 0
        failed = 0
        for row in rows:
            events = row["events"] if isinstance(row["events"], list) else json.loads(row["events"] or "[]")
            for evt in events:
                if evt.get("type") in ("fe_retrieve", "fe_ingest"):
                    total += 1
                    if evt.get("status") == "error":
                        failed += 1

        # 也检查 audit_log 中的 fe 相关错误
        audit_row = await db.fetchrow(
            """
            SELECT COUNT(*) AS cnt
            FROM agent_audit_log
            WHERE created_at >= NOW() - ($1 || ' minutes')::INTERVAL
              AND event_type = 'fe_grpc_error'
            """,
            str(window_minutes),
        )
        if audit_row:
            failed += audit_row["cnt"]
            total += audit_row["cnt"]

        rate = failed / max(total, 1)
        return rate, total, failed

    async def evaluate_all(self) -> list[AlertEvent]:
        """
        评估所有告警规则，返回触发的告警列表。
        """
        alerts: list[AlertEvent] = []

        for rule in ALERT_RULES:
            # 节流检查
            if self._should_throttle(rule.metric):
                continue

            try:
                if rule.metric == "tool_failure_rate":
                    value, total, failed = await self._calculate_tool_failure_rate(rule.window_minutes)
                elif rule.metric == "agent_failure_rate":
                    value, total, failed = await self._calculate_agent_failure_rate(rule.window_minutes)
                elif rule.metric == "llm_p95_latency_s":
                    value, _ = await self._calculate_llm_p95_latency(rule.window_minutes)
                    total = 0
                    failed = 0
                elif rule.metric == "fe_grpc_error_rate":
                    value, total, failed = await self._calculate_fe_grpc_error_rate(rule.window_minutes)
                else:
                    continue

            except Exception as e:
                logger.error(f"[ObservationAlert] failed to calculate {rule.metric}: {e}")
                continue

            # 比较阈值
            triggered = value > rule.threshold

            if triggered:
                message = (
                    f"[{rule.level.value.upper()}] {rule.metric} = {value:.2%} "
                    f"(阈值: {rule.metric == 'llm_p95_latency_s' and f'{rule.threshold}s' or f'{rule.threshold:.0%}'}) "
                    f"total={total} failed={failed} "
                    f"动作: {rule.action}"
                )

                alert = AlertEvent(
                    rule=rule,
                    current_value=value,
                    message=message,
                )
                alerts.append(alert)
                self._mark_alerted(rule.metric)

        return alerts

    async def evaluate_and_persist(self) -> list[AlertEvent]:
        """
        评估告警并写入 agent_audit_log。
        """
        alerts = await self.evaluate_all()

        for alert in alerts:
            logger.warning(f"[ObservationAlert] {alert.message}")

            try:
                await db.execute(
                    """
                    INSERT INTO agent_audit_log (session_id, agent_name, event_type, event_data)
                    VALUES ($1, $2, $3, $4)
                    """,
                    "observation:alert",
                    "observation_alert",
                    "alert_triggered",
                    json.dumps({
                        "metric": alert.rule.metric,
                        "level": alert.rule.level.value,
                        "threshold": alert.rule.threshold,
                        "current_value": alert.current_value,
                        "action": alert.rule.action,
                        "message": alert.message,
                    }, ensure_ascii=False),
                )
            except Exception as e:
                logger.error(f"[ObservationAlert] failed to persist alert: {e}")

        # 特殊处理: CRITICAL 告警时自动降级
        for alert in alerts:
            if alert.rule.level == AlertLevel.CRITICAL and alert.rule.metric == "fe_grpc_error_rate":
                await self._trigger_fe_degradation()

        return alerts

    async def _trigger_fe_degradation(self) -> None:
        """
        触发 FE gRPC 自动降级（无记忆模式）。
        设置 Redis 降级标记，Agent 检测到此标记后跳过 fe_retrieve/fe_ingest 调用。
        """
        try:
            from redis_util import redis_client
            await redis_client.set(
                "observation:fe_degraded",
                json.dumps({
                    "degraded": True,
                    "since": time.time(),
                    "reason": "FE gRPC error rate exceeded 20% threshold",
                }),
                ttl=600,  # 10 分钟后自动恢复
            )
            logger.critical(
                "[ObservationAlert] FE gRPC DEGRADATION activated — "
                "Agent running in memory-less mode for 10 minutes"
            )
        except Exception as e:
            logger.error(f"[ObservationAlert] failed to trigger FE degradation: {e}")

    async def check_fe_degraded(self) -> bool:
        """
        检查 FE gRPC 是否处于降级状态。
        """
        try:
            from redis_util import redis_client
            data = await redis_client.get("observation:fe_degraded")
            if data is None:
                return False
            info = json.loads(data)
            return info.get("degraded", False)
        except Exception:
            return False


# ============================================================
# 便捷函数
# ============================================================


async def run_alert_check() -> list[dict]:
    """
    Cron 定时任务入口：运行告警检查。

    用法:
        asyncio.create_task(run_alert_check())
    """
    engine = ObservationAlertEngine()
    alerts = await engine.evaluate_and_persist()

    return [
        {
            "metric": a.rule.metric,
            "level": a.rule.level.value,
            "value": a.current_value,
            "message": a.message,
        }
        for a in alerts
    ]


# 全局单例
observation_alert_engine = ObservationAlertEngine()
