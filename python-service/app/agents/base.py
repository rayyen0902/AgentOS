"""
BaseAgent 接口定义 + AgentResult / SessionContext 数据结构
"""
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class StatusEvent:
    seq: int
    source: str
    status: Literal["running", "done", "error"]
    label: str
    duration_ms: int = 0
    created_at: str = ""


@dataclass
class InterruptRequest:
    type: str
    question: str
    options: list[str]
    timeout_s: int = 300
    created_at: str = ""


@dataclass
class CardPayload:
    type: Literal["workshop_card", "skin_report_card", "schedule_card", "interrupt_card"]
    data: dict


@dataclass
class AgentResult:
    state: dict
    reply: str
    interrupt: InterruptRequest | None = None
    events: list[StatusEvent] = field(default_factory=list)
    card: CardPayload | None = None
    done: bool = True
    error: str | None = None


@dataclass
class SessionContext:
    session_id: str
    user_id: int
    tenant_id: int
    platform: str
    input: str
    agent_state: dict
    message_type: str = "text"
    image_url: str | None = None


class BaseAgent:
    name: str

    async def run(self, ctx: SessionContext, input: str) -> AgentResult:
        raise NotImplementedError

    async def resume(self, ctx: SessionContext, reply: str) -> AgentResult:
        raise NotImplementedError
