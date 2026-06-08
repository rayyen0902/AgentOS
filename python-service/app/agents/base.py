"""
BaseAgent 接口定义 + AgentResult / SessionContext 数据结构
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

# S2-09: PRD 5.4.1 规定回复最长 1000 字
MAX_REPLY_LENGTH = 1000


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
    type: Literal[
        "workshop_card", "skin_report_card", "schedule_card", "interrupt_card"
    ]
    data: dict


@dataclass
class AgentResult:
    state: dict
    reply: str  # S2-09: max_length=1000 由 routes.py _truncate_reply 保证
    interrupt: InterruptRequest | None = None
    events: list[StatusEvent] = field(default_factory=list)
    card: CardPayload | None = None
    done: bool = True
    error: str | None = None

    # S2-09: 构造时就裁切超长文本
    def __post_init__(self):
        if len(self.reply) > MAX_REPLY_LENGTH:
            self.reply = self.reply[: MAX_REPLY_LENGTH - 3] + "..."


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


# S2-08: name 改为 abstractmethod property，子类忘记实现会 TypeError
class BaseAgent(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def run(self, ctx: SessionContext, input: str) -> AgentResult: ...

    async def resume(self, ctx: SessionContext, reply: str) -> AgentResult:
        raise NotImplementedError
