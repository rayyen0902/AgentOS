"""
Tests for BaseAgent interface and data structures (base.py).
"""
import pytest

from app.agents.base import (
    AgentResult,
    BaseAgent,
    CardPayload,
    InterruptRequest,
    MAX_REPLY_LENGTH,
    SessionContext,
    StatusEvent,
)


# ── AgentResult ──────────────────────────────────────────────────────────────

class TestAgentResult:
    def test_reply_truncated_when_too_long(self):
        long_reply = "x" * 1100
        result = AgentResult(state={}, reply=long_reply)
        expected_len = MAX_REPLY_LENGTH
        assert len(result.reply) == expected_len
        assert result.reply.endswith("...")
        # First part matches (MAX_REPLY_LENGTH - 3) chars of original
        assert result.reply[:-3] == long_reply[:MAX_REPLY_LENGTH - 3]

    def test_reply_not_truncated_when_short(self):
        reply = "x" * 500
        result = AgentResult(state={}, reply=reply)
        assert result.reply == reply
        assert len(result.reply) == 500

    def test_reply_exactly_at_limit(self):
        reply = "x" * MAX_REPLY_LENGTH
        result = AgentResult(state={}, reply=reply)
        # Exactly at limit: len > MAX_REPLY_LENGTH is False, so unchanged
        assert result.reply == reply
        assert len(result.reply) == MAX_REPLY_LENGTH

    def test_default_values(self):
        result = AgentResult(state={}, reply="hello")
        assert result.reply == "hello"
        assert result.state == {}
        assert result.interrupt is None
        assert result.events == []
        assert result.card is None
        assert result.done is True
        assert result.error is None


# ── BaseAgent ─────────────────────────────────────────────────────────────────

class TestBaseAgent:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BaseAgent()  # type: ignore[abstract]

    def test_subclass_must_implement_name(self):
        class NoName(BaseAgent):
            async def run(self, ctx, input):
                return AgentResult(state={}, reply="ok")

        with pytest.raises(TypeError):
            NoName()  # missing abstract property 'name'

    def test_subclass_must_implement_run(self):
        class NoRun(BaseAgent):
            @property
            def name(self) -> str:
                return "no_run"

        with pytest.raises(TypeError):
            NoRun()  # missing abstract method 'run'

    def test_valid_subclass(self):
        class Valid(BaseAgent):
            @property
            def name(self) -> str:
                return "valid"

            async def run(self, ctx, input):
                return AgentResult(state={}, reply="ok")

        instance = Valid()
        assert instance.name == "valid"

    @pytest.mark.asyncio
    async def test_resume_default_raises_not_implemented(self):
        class Minimal(BaseAgent):
            @property
            def name(self) -> str:
                return "minimal"

            async def run(self, ctx, input):
                return AgentResult(state={}, reply="ok")

        agent = Minimal()
        ctx = SessionContext(
            session_id="s1",
            user_id=1,
            tenant_id=1,
            platform="test",
            input="hi",
            agent_state={},
        )
        with pytest.raises(NotImplementedError):
            await agent.resume(ctx, "reply")


# ── SessionContext ────────────────────────────────────────────────────────────

class TestSessionContext:
    def test_default_values(self):
        """Optional fields have expected defaults when omitted."""
        ctx = SessionContext(
            session_id="s1",
            user_id=1,
            tenant_id=1,
            platform="test",
            input="hi",
            agent_state={},
        )
        assert ctx.message_type == "text"
        assert ctx.image_url is None

    def test_all_fields_passed(self):
        ctx = SessionContext(
            session_id="s-abc",
            user_id=42,
            tenant_id=7,
            platform="wecom",
            input="hello world",
            agent_state={"stage": "idle"},
            message_type="image",
            image_url="https://example.com/img.png",
        )
        assert ctx.session_id == "s-abc"
        assert ctx.user_id == 42
        assert ctx.tenant_id == 7
        assert ctx.platform == "wecom"
        assert ctx.input == "hello world"
        assert ctx.agent_state == {"stage": "idle"}
        assert ctx.message_type == "image"
        assert ctx.image_url == "https://example.com/img.png"

    def test_user_id_is_int(self):
        ctx = SessionContext(
            session_id="s1",
            user_id=1,
            tenant_id=1,
            platform="test",
            input="hi",
            agent_state={},
        )
        assert isinstance(ctx.user_id, int)
        assert ctx.user_id == 1

    def test_tenant_id_is_int(self):
        ctx = SessionContext(
            session_id="s1",
            user_id=1,
            tenant_id=99,
            platform="test",
            input="hi",
            agent_state={},
        )
        assert isinstance(ctx.tenant_id, int)
        assert ctx.tenant_id == 99


# ── InterruptRequest ──────────────────────────────────────────────────────────

class TestInterruptRequest:
    def test_create_interrupt(self):
        ir = InterruptRequest(
            type="choice",
            question="请选择肤质",
            options=["油性", "干性", "混合"],
        )
        assert ir.type == "choice"
        assert ir.question == "请选择肤质"
        assert ir.options == ["油性", "干性", "混合"]
        assert ir.timeout_s == 300
        assert ir.created_at == ""

    def test_interrupt_with_empty_options(self):
        ir = InterruptRequest(
            type="confirm",
            question="确认操作?",
            options=[],
        )
        assert ir.options == []
        assert ir.type == "confirm"

    def test_interrupt_custom_timeout(self):
        ir = InterruptRequest(
            type="input",
            question="请输入手机号",
            options=[],
            timeout_s=60,
        )
        assert ir.timeout_s == 60


# ── CardPayload ───────────────────────────────────────────────────────────────

class TestCardPayload:
    def test_create_card(self):
        card = CardPayload(
            type="skin_report_card",
            data={"score": 85, "concerns": ["dryness"]},
        )
        assert card.type == "skin_report_card"
        assert card.data == {"score": 85, "concerns": ["dryness"]}

    def test_card_with_empty_data(self):
        card = CardPayload(type="workshop_card", data={})
        assert card.type == "workshop_card"
        assert card.data == {}


# ── StatusEvent ───────────────────────────────────────────────────────────────

class TestStatusEvent:
    def test_create_status_event(self):
        ev = StatusEvent(
            seq=1,
            source="orchestrator",
            status="running",
            label="正在处理...",
        )
        assert ev.seq == 1
        assert ev.source == "orchestrator"
        assert ev.status == "running"
        assert ev.label == "正在处理..."
        assert ev.duration_ms == 0
        assert ev.created_at == ""

    def test_status_event_with_all_fields(self):
        ev = StatusEvent(
            seq=5,
            source="copywriter",
            status="done",
            label="文案生成完成",
            duration_ms=1234,
            created_at="2025-01-01T00:00:00Z",
        )
        assert ev.seq == 5
        assert ev.source == "copywriter"
        assert ev.status == "done"
        assert ev.label == "文案生成完成"
        assert ev.duration_ms == 1234
        assert ev.created_at == "2025-01-01T00:00:00Z"
