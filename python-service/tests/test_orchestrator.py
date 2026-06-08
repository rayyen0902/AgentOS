"""
Tests for orchestrator.py — intent classification, routing, delegation, resume.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from app.agents.base import (
    AgentResult,
    CardPayload,
    InterruptRequest,
    SessionContext,
    StatusEvent,
)
from app.agents.orchestrator import (
    classify_intent,
    run_orchestrator,
    resume_agent,
    _delegate_to_agent,
    _direct_chat_reply,
)
from app.agents.escalation import (
    EscalationAction,
    EscalationLevel,
    EscalationResult,
)
from app.tools.models import (
    KnowledgeItem,
    ProductCRUDOutput,
    ProductItem,
    RAGSearchOutput,
)


# ── helpers ────────────────────────────────────────────────────────────────────


def _ctx(**overrides):
    defaults = dict(
        session_id="test-session-001",
        user_id=1,
        tenant_id=1,
        platform="test",
        input="你好",
        agent_state={"stage": "idle"},
    )
    defaults.update(overrides)
    return SessionContext(**defaults)


def _make_escalation_result(should_block=True, action=EscalationAction.ESCALATE_SERVICE):
    return EscalationResult(
        level=EscalationLevel.HIGH,
        action=action,
        matched_rule="投诉/退款/法律威胁",
        reason="关键词命中",
        should_block=should_block,
        reply_override="已转接人工客服",
    )


# ── TestRunOrchestrator ────────────────────────────────────────────────────────


class TestRunOrchestrator:
    """run_orchestrator() entry-point tests."""

    @pytest.mark.asyncio
    async def test_escalated_session_returns_immediately(self):
        """Stage=escalated → AgentResult with escalated reply, no LLM call."""
        ctx = _ctx(agent_state={"stage": "escalated"})

        with patch("app.agents.orchestrator.classify_intent") as mock_cls:
            result = await run_orchestrator(ctx, "随便发点什么")

        mock_cls.assert_not_called()
        assert result.done is True
        assert "转接至人工客服" in result.reply
        assert result.state.get("phase") == "escalated"
        assert result.state.get("stage") == "escalated"

    @pytest.mark.asyncio
    async def test_agent_running_returns_busy(self):
        """Stage=agent_running → busy reply, message discarded."""
        ctx = _ctx(agent_state={"stage": "agent_running"})

        with patch("app.agents.orchestrator.classify_intent") as mock_cls:
            result = await run_orchestrator(ctx, "hello")

        mock_cls.assert_not_called()
        assert result.done is True
        assert "稍等" in result.reply
        assert result.state.get("phase") == "busy"

    @pytest.mark.asyncio
    async def test_agent_interrupted_chat_clears_interrupt(self):
        """Stage=agent_interrupted + chat intent → clears interrupt, does NOT
        call resume_agent."""
        ctx = _ctx(agent_state={
            "stage": "agent_interrupted",
            "current_agent": "workshop",
        })

        with patch(
            "app.agents.orchestrator.classify_intent",
            new_callable=AsyncMock,
        ) as mock_cls:
            mock_cls.return_value = {"intent": "chat", "confidence": 0.9}
            result = await run_orchestrator(ctx, "算了不弄了")

        mock_cls.assert_awaited_once_with("算了不弄了")
        assert result.done is True
        assert "退出当前任务" in result.reply
        assert result.state.get("stage") == "idle"
        assert result.state.get("current_agent") is None

    @pytest.mark.asyncio
    async def test_agent_interrupted_non_chat_resumes(self):
        """Stage=agent_interrupted + non-chat → resume_agent called."""
        ctx = _ctx(agent_state={
            "stage": "agent_interrupted",
            "current_agent": "workshop",
        })

        fake_resume_result = AgentResult(
            state={"stage": "agent_running"},
            reply="resumed!",
        )

        with patch(
            "app.agents.orchestrator.classify_intent",
            new_callable=AsyncMock,
        ) as mock_cls:
            mock_cls.return_value = {
                "intent": "recommend_product",
                "confidence": 0.92,
            }
            with patch(
                "app.agents.orchestrator.resume_agent",
                new_callable=AsyncMock,
            ) as mock_resume:
                mock_resume.return_value = fake_resume_result
                result = await run_orchestrator(ctx, "继续推荐")

        mock_cls.assert_awaited_once_with("继续推荐")
        mock_resume.assert_awaited_once()
        # resume_agent(ctx, "workshop", "继续推荐", events, 0)
        call_args = mock_resume.call_args
        assert call_args[0][1] == "workshop"   # agent_type
        assert call_args[0][2] == "继续推荐"    # input
        assert result.reply == "resumed!"

    @pytest.mark.asyncio
    async def test_low_confidence_clarification(self):
        """classify_intent confidence < 0.6 → direct clarification reply."""
        ctx = _ctx()

        with patch(
            "app.agents.orchestrator.classify_intent",
            new_callable=AsyncMock,
        ) as mock_cls:
            mock_cls.return_value = {
                "intent": "some_vague",
                "confidence": 0.35,
                "immediate_reply": "请问您想了解护肤的哪个方面呢？",
            }
            result = await run_orchestrator(ctx, "护肤")

        assert result.done is True
        assert result.state.get("phase") == "clarify"
        assert "护肤" in result.reply
        # Ensure we did NOT call _delegate_to_agent
        assert result.state.get("confidence") == 0.35

    @pytest.mark.asyncio
    async def test_product_crud_intent(self):
        """intent=product_add → calls _direct_tool_product_add."""
        ctx = _ctx()

        fake_result = AgentResult(state={"phase": "tool_direct"}, reply="已记录")

        with patch(
            "app.agents.orchestrator.classify_intent",
            new_callable=AsyncMock,
        ) as mock_cls:
            mock_cls.return_value = {
                "intent": "product_add",
                "confidence": 0.85,
                "extracted_entities": {"product_name": "小棕瓶"},
            }
            with patch(
                "app.agents.orchestrator._direct_tool_product_add",
                new_callable=AsyncMock,
            ) as mock_tool:
                mock_tool.return_value = fake_result
                result = await run_orchestrator(ctx, "我在用小棕瓶")

        mock_cls.assert_awaited_once()
        mock_tool.assert_awaited_once()
        assert result.reply == "已记录"
        assert result.state.get("phase") == "tool_direct"

    @pytest.mark.asyncio
    async def test_rag_search_intent(self):
        """intent=knowledge_query → calls _direct_tool_rag."""
        ctx = _ctx()

        fake_result = AgentResult(state={"phase": "tool_direct"}, reply="知识库说…")

        with patch(
            "app.agents.orchestrator.classify_intent",
            new_callable=AsyncMock,
        ) as mock_cls:
            mock_cls.return_value = {
                "intent": "knowledge_query",
                "confidence": 0.88,
            }
            with patch(
                "app.agents.orchestrator._direct_tool_rag",
                new_callable=AsyncMock,
            ) as mock_tool:
                mock_tool.return_value = fake_result
                result = await run_orchestrator(ctx, "玻尿酸是什么")

        mock_cls.assert_awaited_once()
        mock_tool.assert_awaited_once()
        assert result.reply == "知识库说…"
        assert result.state.get("phase") == "tool_direct"

    @pytest.mark.asyncio
    async def test_delegate_to_agent_intent(self):
        """intent=recommend_product → _delegate_to_agent("workshop")."""
        ctx = _ctx()

        fake_result = AgentResult(state={"stage": "agent_running"}, reply="推荐中…")

        with patch(
            "app.agents.orchestrator.classify_intent",
            new_callable=AsyncMock,
        ) as mock_cls:
            mock_cls.return_value = {
                "intent": "recommend_product",
                "confidence": 0.92,
            }
            with patch(
                "app.agents.orchestrator._delegate_to_agent",
                new_callable=AsyncMock,
            ) as mock_del:
                mock_del.return_value = fake_result
                result = await run_orchestrator(ctx, "帮我推荐产品")

        mock_cls.assert_awaited_once()
        mock_del.assert_awaited_once()
        call_args = mock_del.call_args
        assert call_args[0][2] == "workshop"  # agent_type
        assert result.reply == "推荐中…"

    @pytest.mark.asyncio
    async def test_chat_intent_fallback(self):
        """intent=chat (no routing target) → _direct_chat_reply."""
        ctx = _ctx()

        fake_result = AgentResult(state={"phase": "direct_chat"}, reply="你好呀~")

        with patch(
            "app.agents.orchestrator.classify_intent",
            new_callable=AsyncMock,
        ) as mock_cls:
            mock_cls.return_value = {
                "intent": "chat",
                "confidence": 0.95,
            }
            with patch(
                "app.agents.orchestrator._direct_chat_reply",
                new_callable=AsyncMock,
            ) as mock_chat:
                mock_chat.return_value = fake_result
                result = await run_orchestrator(ctx, "你好")

        mock_cls.assert_awaited_once()
        mock_chat.assert_awaited_once()
        assert result.reply == "你好呀~"
        assert result.state.get("phase") == "direct_chat"


# ── TestClassifyIntent ─────────────────────────────────────────────────────────


class TestClassifyIntent:
    """classify_intent() — LLM call, JSON parse, fallback behaviour."""

    @pytest.mark.asyncio
    async def test_returns_parsed_json(self):
        """Valid JSON from LLM → parsed dict returned."""
        with patch(
            "app.agents.orchestrator.llm_chat", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = '{"intent":"workshop","confidence":0.9}'
            result = await classify_intent("推荐产品")

        assert result["intent"] == "workshop"
        assert result["confidence"] == 0.9

    @pytest.mark.asyncio
    async def test_json_parse_error_fallback(self):
        """Malformed JSON → chat fallback dict (no exception)."""
        with patch(
            "app.agents.orchestrator.llm_chat", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = "not valid json at all"
            result = await classify_intent("blah")

        assert result["intent"] == "chat"
        assert result["confidence"] == 0.3
        assert result["immediate_reply"] == "收到，让我想想~"

    @pytest.mark.asyncio
    async def test_llm_exception_fallback(self):
        """LLM raises → chat fallback, no crash."""
        with patch(
            "app.agents.orchestrator.llm_chat", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.side_effect = Exception("LLM down!")
            result = await classify_intent("hello")

        assert result["intent"] == "chat"
        assert result["confidence"] == 0.3
        assert result["immediate_reply"] == "收到，让我想想~"


# ── TestDirectChatReply ────────────────────────────────────────────────────────


class TestDirectChatReply:
    """_direct_chat_reply() — simple LLM reply or hardcoded fallback."""

    @pytest.mark.asyncio
    async def test_successful_reply(self):
        """LLM returns a reply → AgentResult wraps it."""
        ctx = _ctx()
        events: list[StatusEvent] = []

        with patch(
            "app.agents.orchestrator.llm_chat", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = "你好！有什么可以帮你的？"
            result = await _direct_chat_reply(ctx, "hello", events, 0)

        assert result.reply == "你好！有什么可以帮你的？"
        assert result.done is True
        assert result.state.get("phase") == "direct_chat"
        assert len(result.events) >= 1

    @pytest.mark.asyncio
    async def test_llm_exception_fallback(self):
        """LLM raises → hardcoded fallback reply."""
        ctx = _ctx()
        events: list[StatusEvent] = []

        with patch(
            "app.agents.orchestrator.llm_chat", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.side_effect = Exception("timeout")
            result = await _direct_chat_reply(ctx, "hello", events, 0)

        assert result.reply == "你好呀~ 有什么护肤问题可以随时问我！"
        assert result.done is True


# ── TestDelegateToAgent ────────────────────────────────────────────────────────


class TestDelegateToAgent:
    """_delegate_to_agent() — agent dispatch, timeout, escalation, interrupt."""

    @pytest.mark.asyncio
    async def test_delegates_to_correct_agent(self):
        """agent_type='workshop' → WorkshopAgent.run() called."""
        ctx = _ctx()
        events: list[StatusEvent] = []
        intent_result = {
            "intent": "recommend_product",
            "confidence": 0.92,
            "immediate_reply": "正在为您挑选产品...",
        }

        fake_agent_result = AgentResult(
            state={"stage": "idle"},
            reply="推荐结果...",
        )

        with patch(
            "app.agents.escalation.check_and_escalate", new_callable=AsyncMock
        ) as mock_esc:
            mock_esc.return_value = (
                _make_escalation_result(should_block=False),
                False,
            )
            with patch(
                "app.agents.workshop_agent.WorkshopAgent.run", new_callable=AsyncMock
            ) as mock_run:
                mock_run.return_value = fake_agent_result
                result = await _delegate_to_agent(
                    ctx, "推荐一款精华", "workshop", intent_result, events, 0,
                )

        mock_esc.assert_awaited_once()
        mock_run.assert_awaited_once()
        assert result.reply == "推荐结果..."
        assert result.state.get("stage") == "idle"
        assert result.state.get("current_agent") is None

    @pytest.mark.asyncio
    async def test_unknown_agent_type(self):
        """Unknown agent_type → error AgentResult."""
        ctx = _ctx()
        events: list[StatusEvent] = []
        intent_result = {"intent": "???", "confidence": 0.9}

        with patch(
            "app.agents.escalation.check_and_escalate", new_callable=AsyncMock
        ) as mock_esc:
            mock_esc.return_value = (
                _make_escalation_result(should_block=False),
                False,
            )
            result = await _delegate_to_agent(
                ctx, "test", "ghost_agent", intent_result, events, 0,
            )

        mock_esc.assert_awaited_once()
        assert result.done is True
        assert "暂不可用" in result.reply
        assert result.error is not None
        assert "not found" in (result.error or "")

    @pytest.mark.asyncio
    async def test_timeout(self):
        """agent.run() exceeds timeout → timeout AgentResult."""
        ctx = _ctx()
        events: list[StatusEvent] = []
        intent_result = {"intent": "recommend_product", "confidence": 0.92}

        with patch(
            "app.agents.escalation.check_and_escalate", new_callable=AsyncMock
        ) as mock_esc:
            mock_esc.return_value = (
                _make_escalation_result(should_block=False),
                False,
            )
            with patch(
                "app.agents.orchestrator.asyncio.wait_for",
                side_effect=asyncio.TimeoutError(),
            ):
                result = await _delegate_to_agent(
                    ctx, "推荐一款精华", "workshop", intent_result, events, 0,
                )

        mock_esc.assert_awaited_once()
        assert result.done is True
        assert "超时" in result.reply
        assert result.error is not None
        assert "timeout" in (result.error or "")
        assert result.state.get("phase") == "timeout"

    @pytest.mark.asyncio
    async def test_generic_exception(self):
        """agent.run() raises → error AgentResult."""
        ctx = _ctx()
        events: list[StatusEvent] = []
        intent_result = {"intent": "recommend_product", "confidence": 0.92}

        with patch(
            "app.agents.escalation.check_and_escalate", new_callable=AsyncMock
        ) as mock_esc:
            mock_esc.return_value = (
                _make_escalation_result(should_block=False),
                False,
            )
            with patch(
                "app.agents.workshop_agent.WorkshopAgent.run",
                new_callable=AsyncMock,
            ) as mock_run:
                mock_run.side_effect = RuntimeError("BOOM")
                result = await _delegate_to_agent(
                    ctx, "推荐一款精华", "workshop", intent_result, events, 0,
                )

        mock_esc.assert_awaited_once()
        assert result.done is True
        assert "暂时不可用" in result.reply
        assert result.error == "BOOM"
        assert result.state.get("phase") == "error"

    @pytest.mark.asyncio
    async def test_agent_interrupt(self):
        """agent.run() returns AgentResult with interrupt → stage=agent_interrupted."""
        ctx = _ctx()
        events: list[StatusEvent] = []
        intent_result = {"intent": "recommend_product", "confidence": 0.92}

        interrupt = InterruptRequest(
            type="choice",
            question="请确认",
            options=["是", "否"],
        )
        fake_result = AgentResult(
            state={},
            reply="需要确认",
            interrupt=interrupt,
        )

        with patch(
            "app.agents.escalation.check_and_escalate", new_callable=AsyncMock
        ) as mock_esc:
            mock_esc.return_value = (
                _make_escalation_result(should_block=False),
                False,
            )
            with patch(
                "app.agents.workshop_agent.WorkshopAgent.run",
                new_callable=AsyncMock,
            ) as mock_run:
                mock_run.return_value = fake_result
                result = await _delegate_to_agent(
                    ctx, "推荐一款精华", "workshop", intent_result, events, 0,
                )

        mock_esc.assert_awaited_once()
        assert result.interrupt is not None
        assert result.interrupt.question == "请确认"
        assert result.state.get("stage") == "agent_interrupted"
        assert result.state.get("current_agent") == "workshop"
        assert "interrupt_started_at" in result.state

    @pytest.mark.asyncio
    async def test_agent_completes(self):
        """agent.run() returns normal result (no interrupt) → stage=idle."""
        ctx = _ctx()
        events: list[StatusEvent] = []
        intent_result = {"intent": "recommend_product", "confidence": 0.92}

        fake_result = AgentResult(
            state={},
            reply="推荐完成",
        )

        with patch(
            "app.agents.escalation.check_and_escalate", new_callable=AsyncMock
        ) as mock_esc:
            mock_esc.return_value = (
                _make_escalation_result(should_block=False),
                False,
            )
            with patch(
                "app.agents.workshop_agent.WorkshopAgent.run",
                new_callable=AsyncMock,
            ) as mock_run:
                mock_run.return_value = fake_result
                result = await _delegate_to_agent(
                    ctx, "推荐一款精华", "workshop", intent_result, events, 0,
                )

        mock_esc.assert_awaited_once()
        assert result.interrupt is None
        assert result.state.get("stage") == "idle"
        assert result.state.get("current_agent") is None

    @pytest.mark.asyncio
    async def test_escalation_blocks(self):
        """check_and_escalate returns should_block=True → blocking reply, agent NOT called."""
        ctx = _ctx()
        events: list[StatusEvent] = []
        intent_result = {"intent": "recommend_product", "confidence": 0.92}

        with patch(
            "app.agents.escalation.check_and_escalate", new_callable=AsyncMock
        ) as mock_esc:
            esc_result = _make_escalation_result(
                should_block=True,
                action=EscalationAction.ESCALATE_SERVICE,
            )
            mock_esc.return_value = (esc_result, True)
            with patch(
                "app.agents.workshop_agent.WorkshopAgent.run", new_callable=AsyncMock
            ) as mock_run:
                result = await _delegate_to_agent(
                    ctx, "我要投诉", "workshop", intent_result, events, 0,
                )

        mock_esc.assert_awaited_once()
        mock_run.assert_not_called()
        assert result.done is True
        assert "已转接人工客服" in result.reply
        assert result.state.get("stage") == "escalated"


# ── TestResumeAgent ────────────────────────────────────────────────────────────


class TestResumeAgent:
    """resume_agent() — interrupt recovery routing."""

    @pytest.mark.asyncio
    async def test_resumes_correct_agent(self):
        """agent_type='workshop' → WorkshopAgent.resume() called."""
        ctx = _ctx(agent_state={"stage": "agent_interrupted"})
        events: list[StatusEvent] = []

        fake_result = AgentResult(
            state={"stage": "idle"},
            reply="已恢复",
        )

        with patch(
            "app.agents.workshop_agent.WorkshopAgent.resume",
            new_callable=AsyncMock,
        ) as mock_resume:
            mock_resume.return_value = fake_result
            result = await resume_agent(ctx, "workshop", "继续", events, 0)

        mock_resume.assert_awaited_once_with(ctx, "继续")
        assert result.reply == "已恢复"
        assert result.state.get("stage") == "idle"

    @pytest.mark.asyncio
    async def test_unknown_agent_returns_error(self):
        """Unknown agent_type → error AgentResult."""
        ctx = _ctx()
        events: list[StatusEvent] = []

        result = await resume_agent(ctx, "ghost", "继续", events, 0)

        assert result.done is True
        assert "暂不可用" in result.reply
        assert result.error is not None
        assert "ghost" in (result.error or "")

    @pytest.mark.asyncio
    async def test_timeout_returns_timeout_reply(self):
        """resume() times out → timeout AgentResult."""
        ctx = _ctx()
        events: list[StatusEvent] = []

        with patch(
            "app.agents.orchestrator.asyncio.wait_for",
            side_effect=asyncio.TimeoutError(),
        ):
            result = await resume_agent(ctx, "workshop", "继续", events, 0)

        assert result.done is True
        assert "超时" in result.reply
        assert result.error is not None
        assert "timeout" in (result.error or "")
