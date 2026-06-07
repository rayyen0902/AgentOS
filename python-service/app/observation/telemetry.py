"""
Observation Telemetry 基础埋点
"""
import json
import logging
import time
import uuid
from dataclasses import dataclass, field

from config import settings

logger = logging.getLogger(__name__)


@dataclass
class TraceEvent:
    trace_id: str
    session_id: str
    agent: str
    events: list[dict] = field(default_factory=list)
    total_ms: int = 0
    user_feedback: str | None = None
    tenant_id: int | None = None


class Telemetry:
    def __init__(self):
        self._traces: dict[str, TraceEvent] = {}

    async def start_trace(
        self, session_id: str, agent: str, tenant_id: int | None = None
    ) -> str:
        trace_id = "tr_" + uuid.uuid4().hex[:12]
        self._traces[trace_id] = TraceEvent(
            trace_id=trace_id,
            session_id=session_id,
            agent=agent,
            tenant_id=tenant_id,
        )
        return trace_id

    async def add_event(self, trace_id: str, event: dict) -> None:
        if trace_id in self._traces:
            self._traces[trace_id].events.append(event)

    async def finish_trace(self, trace_id: str, total_ms: int) -> None:
        if trace_id in self._traces:
            self._traces[trace_id].total_ms = total_ms

    async def flush_to_db(self, trace_id: str) -> None:
        if trace_id not in self._traces:
            return
        trace = self._traces[trace_id]
        if not settings.TRACE_ENABLED:
            del self._traces[trace_id]
            return

        try:
            from db_util import db

            await db.execute(
                """
                INSERT INTO observation_traces (trace_id, session_id, tenant_id, agent, events, total_ms)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (trace_id) DO UPDATE
                SET events = $5, total_ms = $6
                """,
                trace.trace_id,
                trace.session_id,
                trace.tenant_id,
                trace.agent,
                json.dumps(trace.events, ensure_ascii=False),
                trace.total_ms,
            )

            logger.debug(
                f"[Telemetry] flushed trace={trace.trace_id} "
                f"agent={trace.agent} events={len(trace.events)} total_ms={trace.total_ms}"
            )
        except Exception as e:
            logger.error(f"[Telemetry] flush_to_db failed for trace={trace_id}: {e}")
        finally:
            del self._traces[trace_id]

    async def add_tool_call(
        self, trace_id: str, tool_name: str, duration_ms: int, status: str = "ok"
    ) -> None:
        """记录 Tool 调用事件"""
        await self.add_event(trace_id, {
            "type": "tool_call",
            "tool": tool_name,
            "duration_ms": duration_ms,
            "status": status,
            "timestamp": time.time(),
        })

    async def add_llm_call(
        self, trace_id: str, model: str, duration_ms: int, status: str = "ok"
    ) -> None:
        """记录 LLM 调用事件（用于 p95 延迟统计）"""
        await self.add_event(trace_id, {
            "type": "llm_call",
            "model": model,
            "duration_ms": duration_ms,
            "status": status,
            "timestamp": time.time(),
        })


telemetry = Telemetry()
