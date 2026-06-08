"""
Tests for Reflection Agent (Step 8 / 8.1).
Covers: should_trigger_reflection, ReflectionAgent.reflect, reflection_and_persist, trigger_reflection_async.
"""
import json
import pytest
from unittest.mock import AsyncMock, patch

from app.agents.base import SessionContext, AgentResult, CardPayload
from app.agents.reflection import (
    Reflection,
    ReflectionAgent,
    should_trigger_reflection,
    trigger_reflection_async,
)


# ── helpers ──────────────────────────────────────────────────────────

def _make_agent() -> ReflectionAgent:
    return ReflectionAgent()


def _make_ctx(**overrides) -> SessionContext:
    defaults = dict(
        session_id="test-session-001",
        user_id=1,
        tenant_id=1,
        platform="test",
        input="你好",
        agent_state={},
    )
    defaults.update(overrides)
    return SessionContext(**defaults)


def _make_result(
    *,
    card: CardPayload | None = None,
    error: str | None = None,
    state: dict | None = None,
    reply: str = "mock reply",
) -> AgentResult:
    return AgentResult(
        state=state or {},
        reply=reply,
        card=card,
        done=True,
        error=error,
    )


# ─────────────────────────────────────────────────────────────────────
# TestShouldTriggerReflection
# ─────────────────────────────────────────────────────────────────────

class TestShouldTriggerReflection:
    """Tests for should_trigger_reflection(result, agent_name) → bool."""

    def test_card_type_in_triggers(self):
        """Result has a card with type in REFLECTION_TRIGGER_SOURCES → True."""
        result = _make_result(
            card=CardPayload(type="workshop_card", data={}),
        )
        assert should_trigger_reflection(result, "配药师") is True

    def test_skin_report_card_triggers(self):
        """skin_report_card type also triggers reflection."""
        result = _make_result(
            card=CardPayload(type="skin_report_card", data={}),
        )
        assert should_trigger_reflection(result, "识肤师") is True

    def test_result_error_returns_false(self):
        """Any non-None error → False, regardless of card."""
        result = _make_result(
            error="timeout",
            card=CardPayload(type="workshop_card", data={}),
        )
        assert should_trigger_reflection(result, "配药师") is False

    def test_diagnosis_step_gte_7(self):
        """Diagnosis agent with diagnosis_step >= 7 → True."""
        result = _make_result(
            state={"diagnosis_step": 7},
        )
        assert should_trigger_reflection(result, "问卷师") is True

    def test_diagnosis_step_gt_7(self):
        """Diagnosis agent with diagnosis_step > 7 → still True."""
        result = _make_result(
            state={"diagnosis_step": 8},
        )
        assert should_trigger_reflection(result, "diagnosis") is True

    def test_diagnosis_step_lt_7(self):
        """Diagnosis agent with diagnosis_step < 7 → False."""
        result = _make_result(
            state={"diagnosis_step": 6},
        )
        assert should_trigger_reflection(result, "问卷师") is False

    def test_diagnosis_no_step_key(self):
        """Diagnosis agent with no 'diagnosis_step' in state → False (defaults to 0)."""
        result = _make_result(state={})
        assert should_trigger_reflection(result, "问卷师") is False

    def test_no_card_not_diagnosis(self):
        """No card and not a diagnosis agent → False."""
        result = _make_result()
        assert should_trigger_reflection(result, "前台Agent") is False

    def test_interrupt_card_does_not_trigger(self):
        """Card type 'interrupt_card' is NOT in REFLECTION_TRIGGER_SOURCES → False."""
        result = _make_result(
            card=CardPayload(type="interrupt_card", data={}),
        )
        assert should_trigger_reflection(result, "前台") is False


# ─────────────────────────────────────────────────────────────────────
# TestReflectionAgentReflect
# ─────────────────────────────────────────────────────────────────────

class TestReflectionAgentReflect:
    """Tests for ReflectionAgent.reflect(ctx, result, agent_name, tool_calls) → Reflection."""

    @pytest.fixture
    def ctx(self) -> SessionContext:
        return _make_ctx(input="我的皮肤好像过敏了")

    @pytest.fixture
    def result(self) -> AgentResult:
        return _make_result(
            reply="建议您停止使用产品并观察...",
            card=CardPayload(type="workshop_card", data={}),
        )

    @pytest.mark.asyncio
    async def test_llm_valid_json(self, ctx, result):
        """LLM returns valid JSON → correct Reflection object with parsed fields."""
        agent = _make_agent()
        llm_response = json.dumps({
            "satisfaction": "high",
            "lesson": "Agent 准确识别了过敏症状并给出保守建议",
            "new_rule": "当用户描述过敏时总是建议停用产品",
            "risk_level": "high",
            "risk_detail": "用户描述了过敏症状，需要关注",
        })

        with patch(
            "app.agents.reflection.llm_chat", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = llm_response
            reflection = await agent.reflect(ctx, result, "配药师")

        assert isinstance(reflection, Reflection)
        assert reflection.satisfaction == "high"
        assert "准确识别" in reflection.lesson
        assert reflection.rule_candidate == "当用户描述过敏时总是建议停用产品"
        assert reflection.should_escalate is True   # risk_level "high"
        assert reflection.risk_level == "high"
        assert reflection.raw_analysis["satisfaction"] == "high"

    @pytest.mark.asyncio
    async def test_llm_medium_satisfaction(self, ctx, result):
        """risk_level 'medium' → should_escalate is False."""
        agent = _make_agent()
        llm_response = json.dumps({
            "satisfaction": "medium",
            "lesson": "回复基本相关但不够具体",
            "new_rule": None,
            "risk_level": "medium",
            "risk_detail": "成分过敏确认",
        })

        with patch(
            "app.agents.reflection.llm_chat", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = llm_response
            reflection = await agent.reflect(ctx, result, "配药师")

        assert reflection.satisfaction == "medium"
        assert reflection.should_escalate is False
        assert reflection.risk_level == "medium"

    @pytest.mark.asyncio
    async def test_llm_parse_error(self, ctx, result):
        """LLM returns invalid JSON → fallback Reflection with default values."""
        agent = _make_agent()

        with patch(
            "app.agents.reflection.llm_chat", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = "this is not json {{{bad"
            reflection = await agent.reflect(ctx, result, "配药师")

        assert reflection.satisfaction == "medium"
        assert "解析失败" in reflection.lesson or "parse" in reflection.lesson.lower()
        assert reflection.rule_candidate is None
        assert reflection.should_escalate is False
        assert reflection.risk_level == "none"

    @pytest.mark.asyncio
    async def test_llm_timeout(self, ctx, result):
        """LLM raises TimeoutError → propagates (reflect() only catches JSONDecodeError/KeyError).

        The broader reflect_and_persist() catches Exception to safely return None.
        Here we test reflect() directly, so TimeoutError propagates.
        """
        agent = _make_agent()

        with patch(
            "app.agents.reflection.llm_chat", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.side_effect = TimeoutError("LLM timed out")
            with pytest.raises(TimeoutError):
                await agent.reflect(ctx, result, "配药师")

    @pytest.mark.asyncio
    async def test_db_insert_failure_is_caught(self, ctx, result):
        """reflect_and_persist catches Exception during db insert → returns None."""
        agent = _make_agent()
        llm_response = json.dumps({
            "satisfaction": "high",
            "lesson": "good",
            "new_rule": None,
            "risk_level": "none",
            "risk_detail": None,
        })

        with patch(
            "app.agents.reflection.llm_chat", new_callable=AsyncMock
        ) as mock_llm, patch(
            "app.agents.reflection.db", new_callable=AsyncMock
        ) as mock_db:
            mock_llm.return_value = llm_response
            mock_db.execute = AsyncMock(side_effect=RuntimeError("DB down"))

            reflection = await agent.reflect_and_persist(ctx, result, "配药师")

        assert reflection is None

    @pytest.mark.asyncio
    async def test_emergency_risk(self, ctx, result):
        """risk_level 'emergency' → should_escalate is True."""
        agent = _make_agent()
        llm_response = json.dumps({
            "satisfaction": "low",
            "lesson": "用户描述了严重不良反应",
            "new_rule": None,
            "risk_level": "emergency",
            "risk_detail": "用户提到烂脸和呼吸困难",
        })

        with patch(
            "app.agents.reflection.llm_chat", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = llm_response
            reflection = await agent.reflect(ctx, result, "配药师")

        assert reflection.risk_level == "emergency"
        assert reflection.should_escalate is True


# ─────────────────────────────────────────────────────────────────────
# TestReflectionAgentReflectAndPersist
# ─────────────────────────────────────────────────────────────────────

class TestReflectionAgentReflectAndPersist:
    """Tests for ReflectionAgent.reflect_and_persist(ctx, result, ...) → Reflection | None."""

    @pytest.fixture
    def ctx(self) -> SessionContext:
        return _make_ctx(input="帮我推荐一款精华", session_id="sess-001")

    @pytest.fixture
    def result(self) -> AgentResult:
        return _make_result(
            reply="推荐您使用玻尿酸精华...",
            card=CardPayload(type="workshop_card", data={}),
        )

    @pytest.mark.asyncio
    async def test_persists_to_audit_log(self, ctx, result):
        """Reflection success → INSERT into agent_audit_log with correct fields."""
        agent = _make_agent()
        llm_response = json.dumps({
            "satisfaction": "high",
            "lesson": "准确推荐",
            "new_rule": None,
            "risk_level": "none",
            "risk_detail": None,
        })

        with patch(
            "app.agents.reflection.llm_chat", new_callable=AsyncMock
        ) as mock_llm, patch(
            "app.agents.reflection.db", new_callable=AsyncMock
        ) as mock_db:
            mock_llm.return_value = llm_response
            mock_db.execute = AsyncMock()

            reflection = await agent.reflect_and_persist(ctx, result, "配药师")

        assert reflection is not None
        assert reflection.satisfaction == "high"
        # Verify audit log insert
        assert mock_db.execute.called
        insert_call = mock_db.execute.call_args
        args_str = str(insert_call)
        assert "INSERT INTO agent_audit_log" in args_str
        assert "sess-001" in args_str
        assert "reflection_complete" in args_str
        # S8-09: agent_name is "reflection:配药师"
        assert "reflection:配药师" in args_str

    @pytest.mark.asyncio
    async def test_returns_none_on_llm_failure(self, ctx, result):
        """LLM exception → reflect_and_persist returns None (no crash)."""
        agent = _make_agent()

        with patch(
            "app.agents.reflection.llm_chat", new_callable=AsyncMock
        ) as mock_llm, patch(
            "app.agents.reflection.db", new_callable=AsyncMock
        ) as mock_db:
            mock_llm.side_effect = RuntimeError("LLM fatal error")
            mock_db.execute = AsyncMock()

            reflection = await agent.reflect_and_persist(ctx, result, "配药师")

        assert reflection is None
        # No audit log insert on failure (reflect_and_persist catches internally)
        insert_calls = [
            c for c in mock_db.execute.call_args_list
            if "INSERT INTO agent_audit_log" in str(c)
        ]
        assert len(insert_calls) == 0


# ─────────────────────────────────────────────────────────────────────
# TestTriggerReflectionAsync
# ─────────────────────────────────────────────────────────────────────

class TestTriggerReflectionAsync:
    """Tests for trigger_reflection_async(ctx, result, agent_name, tool_calls) → None."""

    @pytest.fixture
    def ctx(self) -> SessionContext:
        return _make_ctx(
            input="帮我配一款面霜",
            session_id="sess-001",
            user_id=1,
            tenant_id=1,
        )

    @pytest.mark.asyncio
    async def test_not_triggered_when_should_not(self, ctx):
        """Condition not met → trigger_reflection_async returns early (no LLM call)."""
        result = _make_result(error="timeout")  # error → should_trigger_reflection=False

        with patch(
            "app.agents.reflection.llm_chat", new_callable=AsyncMock
        ) as mock_llm, patch(
            "app.agents.reflection.db", new_callable=AsyncMock
        ) as mock_db, patch(
            "app.agents.memory_consolidation.trigger_memory_consolidation_async",
            new_callable=AsyncMock,
        ) as _mock_consolidation:
            mock_db.execute = AsyncMock()
            await trigger_reflection_async(ctx, result, "配药师")

        # LLM should NEVER be called because trigger condition not met
        mock_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_triggered_when_should(self, ctx):
        """Condition met → reflection runs, persists to audit log, triggers consolidation."""
        result = _make_result(
            card=CardPayload(type="workshop_card", data={}),
        )
        llm_response = json.dumps({
            "satisfaction": "high",
            "lesson": "Workshop card 推送成功",
            "new_rule": None,
            "risk_level": "none",
            "risk_detail": None,
        })

        with patch(
            "app.agents.reflection.llm_chat", new_callable=AsyncMock
        ) as mock_llm, patch(
            "app.agents.reflection.db", new_callable=AsyncMock
        ) as mock_db, patch(
            "app.agents.memory_consolidation.trigger_memory_consolidation_async",
            new_callable=AsyncMock,
        ) as mock_consolidation:
            mock_llm.return_value = llm_response
            mock_db.execute = AsyncMock()

            await trigger_reflection_async(ctx, result, "配药师")

        # LLM was called
        mock_llm.assert_called_once()
        # Audit log was inserted
        insert_calls = [
            c for c in mock_db.execute.call_args_list
            if "INSERT INTO agent_audit_log" in str(c)
        ]
        assert len(insert_calls) == 1
        # consolidation was triggered
        mock_consolidation.assert_called_once()

    @pytest.mark.asyncio
    async def test_high_risk_triggers_escalate_flag(self, ctx):
        """Reflection detects high risk → should_escalate=True (but no escalation engine call in this flow)."""
        result = _make_result(
            card=CardPayload(type="skin_report_card", data={}),
        )
        llm_response = json.dumps({
            "satisfaction": "low",
            "lesson": "用户描述了严重过敏",
            "new_rule": "必须检测过敏关键词",
            "risk_level": "high",
            "risk_detail": "用户面部红肿",
        })

        with patch(
            "app.agents.reflection.llm_chat", new_callable=AsyncMock
        ) as mock_llm, patch(
            "app.agents.reflection.db", new_callable=AsyncMock
        ) as mock_db, patch(
            "app.agents.memory_consolidation.trigger_memory_consolidation_async",
            new_callable=AsyncMock,
        ) as mock_consolidation:
            mock_llm.return_value = llm_response
            mock_db.execute = AsyncMock()

            await trigger_reflection_async(ctx, result, "识肤师")

        # Should complete without error — risk flags are set but handled upstream
        mock_llm.assert_called_once()
        mock_consolidation.assert_called_once()
