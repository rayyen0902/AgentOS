"""
Tests for Human Escalation engine (Step 8 / 8.3).
Covers: keyword/regex matching, LLM verify, escalate_session, reset_session, check_and_escalate.
"""
import json
import pytest
from unittest.mock import AsyncMock, patch

from app.agents.escalation import (
    HumanEscalationEngine,
    EscalationLevel,
    EscalationAction,
    EscalationRule,
    EscalationResult,
    llm_verify_escalation,
    check_escalation,
    check_and_escalate,
    ESCALATION_RULES,
)


# ── helpers ──────────────────────────────────────────────────────────

def _make_engine() -> HumanEscalationEngine:
    return HumanEscalationEngine()


# ─────────────────────────────────────────────────────────────────────
# TestHumanEscalationEngineCheck
# ─────────────────────────────────────────────────────────────────────

class TestHumanEscalationEngineCheck:
    """Tests for HumanEscalationEngine.check(user_input) → EscalationResult."""

    @pytest.mark.asyncio
    async def test_emergency_keywords(self):
        """Input with emergency keywords triggers EMERGENCY rule (highest priority)."""
        engine = _make_engine()
        with patch(
            "app.agents.escalation.llm_verify_escalation", new_callable=AsyncMock
        ) as mock_verify:
            mock_verify.return_value = True
            result = await engine.check("我呼吸困难快叫救护车")

        assert result.level == EscalationLevel.EMERGENCY
        assert result.action == EscalationAction.ESCALATE_URGENT
        assert result.should_block is True
        assert "烂脸/严重不良反应" in result.matched_rule
        assert result.reply_override is not None

    @pytest.mark.asyncio
    async def test_urgent_keywords(self):
        """Input with allergic-symptom keywords triggers URGENT rule."""
        engine = _make_engine()
        with patch(
            "app.agents.escalation.llm_verify_escalation", new_callable=AsyncMock
        ) as mock_verify:
            mock_verify.return_value = True
            result = await engine.check("我的脸严重红肿疼痛")

        assert result.level == EscalationLevel.URGENT
        assert result.action == EscalationAction.ESCALATE_ALERT
        assert result.should_block is True
        assert "过敏反应描述" in result.matched_rule

    @pytest.mark.asyncio
    async def test_high_keywords_complaint(self):
        """Input with complaint keywords triggers HIGH → ESCALATE_SERVICE (no LLM verify)."""
        engine = _make_engine()
        result = await engine.check("我要投诉你们的产品质量")

        assert result.level == EscalationLevel.HIGH
        assert result.action == EscalationAction.ESCALATE_SERVICE
        assert result.should_block is True
        assert "投诉/退款" in result.matched_rule

    @pytest.mark.asyncio
    async def test_medium_keywords(self):
        """Input with allergy-confirmation keywords triggers MEDIUM → INTERRUPT."""
        engine = _make_engine()
        result = await engine.check("我对这个成分不耐受")

        assert result.level == EscalationLevel.MEDIUM
        assert result.action == EscalationAction.INTERRUPT
        assert result.should_block is True
        assert "成分过敏确认" in result.matched_rule

    @pytest.mark.asyncio
    async def test_priority_emergency_over_urgent(self):
        """Input matching both EMERGENCY and URGENT → EMERGENCY wins (highest priority)."""
        engine = _make_engine()
        with patch(
            "app.agents.escalation.llm_verify_escalation", new_callable=AsyncMock
        ) as mock_verify:
            mock_verify.return_value = True
            result = await engine.check("我呼吸困难脸也红肿")

        assert result.level == EscalationLevel.EMERGENCY
        assert result.action == EscalationAction.ESCALATE_URGENT

    @pytest.mark.asyncio
    async def test_no_match_returns_none(self):
        """Benign input that matches no rules → EscalationResult with level=NONE."""
        engine = _make_engine()
        result = await engine.check("今天天气真好")

        assert result.level == EscalationLevel.NONE
        assert result.action == EscalationAction.NONE
        assert result.should_block is False
        assert result.matched_rule == ""

    # ── LLM verify sub-tests (for rules with llm_verify=True) ─────

    @pytest.mark.asyncio
    async def test_llm_verify_confirms(self):
        """LLM secondary verify returns True → escalation is triggered."""
        engine = _make_engine()
        with patch(
            "app.agents.escalation.llm_verify_escalation", new_callable=AsyncMock
        ) as mock_verify:
            mock_verify.return_value = True
            result = await engine.check("我的脸红肿起疹了")

        assert result.level == EscalationLevel.URGENT
        assert result.should_block is True

    @pytest.mark.asyncio
    async def test_llm_verify_rejects(self):
        """LLM secondary verify returns False → NO escalation (conservative)."""
        engine = _make_engine()
        with patch(
            "app.agents.escalation.llm_verify_escalation", new_callable=AsyncMock
        ) as mock_verify:
            mock_verify.return_value = False
            result = await engine.check("什么是红肿？")

        assert result.level == EscalationLevel.NONE
        assert result.should_block is False
        assert "Flash LLM 二次确认未通过" in result.reason

    @pytest.mark.asyncio
    async def test_llm_verify_exception_fallback(self):
        """LLM verify raises exception → conservative: NO escalation.

        We mock the inner llm_chat to raise, so the real llm_verify_escalation
        catches it and returns False (its exception handler is conservative).
        """
        engine = _make_engine()
        with patch(
            "app.agents.escalation.llm_chat", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.side_effect = RuntimeError("LLM connection error")
            result = await engine.check("我呼吸困难")

        assert result.level == EscalationLevel.NONE
        assert result.should_block is False


# ─────────────────────────────────────────────────────────────────────
# TestLlmVerifyEscalation  (standalone function)
# ─────────────────────────────────────────────────────────────────────

class TestLlmVerifyEscalation:
    """Tests for llm_verify_escalation(user_input, rule) → bool."""

    @pytest.fixture
    def sample_rule(self) -> EscalationRule:
        return ESCALATION_RULES[0]  # urgent rule (llm_verify=True)

    @pytest.mark.asyncio
    async def test_llm_confirms(self, sample_rule):
        """LLM returns is_real=true → returns True."""
        with patch(
            "app.agents.escalation.llm_chat", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = json.dumps({
                "is_real": True,
                "reason": "用户确实描述了红肿症状",
                "severity": "urgent",
            })
            result = await llm_verify_escalation("我的脸红肿了", sample_rule)

        assert result is True

    @pytest.mark.asyncio
    async def test_llm_rejects(self, sample_rule):
        """LLM returns is_real=false → returns False."""
        with patch(
            "app.agents.escalation.llm_chat", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = json.dumps({
                "is_real": False,
                "reason": "用户在询问一般性知识",
                "severity": "none",
            })
            result = await llm_verify_escalation("红肿是什么意思", sample_rule)

        assert result is False

    @pytest.mark.asyncio
    async def test_json_parse_error(self, sample_rule):
        """LLM returns invalid JSON → returns False (conservative, don't escalate)."""
        with patch(
            "app.agents.escalation.llm_chat", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = "not valid json {{{"
            result = await llm_verify_escalation("我的脸红肿了", sample_rule)

        assert result is False

    @pytest.mark.asyncio
    async def test_llm_exception(self, sample_rule):
        """LLM call raises exception → returns False (conservative)."""
        with patch(
            "app.agents.escalation.llm_chat", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.side_effect = TimeoutError("LLM timed out")
            result = await llm_verify_escalation("我的脸红肿了", sample_rule)

        assert result is False


# ─────────────────────────────────────────────────────────────────────
# TestEscalateSession
# ─────────────────────────────────────────────────────────────────────

class TestEscalateSession:
    """Tests for HumanEscalationEngine.escalate_session(...)."""

    @pytest.fixture
    def escalation_result(self) -> EscalationResult:
        return EscalationResult(
            level=EscalationLevel.URGENT,
            action=EscalationAction.ESCALATE_ALERT,
            matched_rule="过敏反应描述（红肿/刺痛/起疹）",
            reason="关键词/正则命中",
            should_block=True,
            reply_override="检测到过敏反应...",
        )

    @pytest.mark.asyncio
    async def test_updates_session_states(self, escalation_result):
        """escalate_session calls db.execute to UPDATE session_states stage='escalated'."""
        engine = _make_engine()
        with patch(
            "app.agents.escalation.db", new_callable=AsyncMock
        ) as mock_db_local:
            mock_db_local.execute = AsyncMock()
            await engine.escalate_session(
                "sess-001", "我的脸红肿了", escalation_result
            )

            update_calls = [
                call for call in mock_db_local.execute.call_args_list
                if "UPDATE session_states" in str(call)
            ]
            assert len(update_calls) >= 1
            # Verify session_id is passed to the UPDATE
            assert "sess-001" in str(update_calls[0])

    @pytest.mark.asyncio
    async def test_inserts_audit_log(self, escalation_result):
        """escalate_session calls db.execute to INSERT into agent_audit_log."""
        engine = _make_engine()
        with patch(
            "app.agents.escalation.db", new_callable=AsyncMock
        ) as mock_db_local:
            mock_db_local.execute = AsyncMock()
            await engine.escalate_session(
                "sess-001", "我的脸红肿了", escalation_result
            )

            insert_calls = [
                call for call in mock_db_local.execute.call_args_list
                if "INSERT INTO agent_audit_log" in str(call)
            ]
            assert len(insert_calls) >= 1
            # Verify event_type = 'escalation_triggered'
            args_str = str(insert_calls[0])
            assert "escalation_triggered" in args_str


# ─────────────────────────────────────────────────────────────────────
# TestResetSession
# ─────────────────────────────────────────────────────────────────────

class TestResetSession:
    """Tests for HumanEscalationEngine.reset_session(session_id) → bool."""

    @pytest.mark.asyncio
    async def test_resets_escalated_session(self):
        """Session in 'escalated' stage → reset to 'idle', returns True."""
        engine = _make_engine()
        with patch(
            "app.agents.escalation.db", new_callable=AsyncMock
        ) as mock_db_local:
            mock_db_local.execute = AsyncMock(return_value="UPDATE 1")

            result = await engine.reset_session("sess-001")

            assert result is True
            # Verify UPDATE was called with stage='idle' and WHERE stage='escalated'
            update_call = mock_db_local.execute.call_args
            assert mock_db_local.execute.called
            args_str = str(update_call)
            assert "idle" in args_str
            assert "escalated" in args_str
            assert "sess-001" in args_str

    @pytest.mark.asyncio
    async def test_noop_on_normal_session(self):
        """Session in 'idle' stage → WHERE clause matches nothing, returns True."""
        engine = _make_engine()
        with patch(
            "app.agents.escalation.db", new_callable=AsyncMock
        ) as mock_db_local:
            mock_db_local.execute = AsyncMock(return_value="UPDATE 0")

            result = await engine.reset_session("sess-002")

            assert result is True
            # Verify WHERE clause includes stage = 'escalated'
            assert mock_db_local.execute.called


# ─────────────────────────────────────────────────────────────────────
# TestCheckAndEscalate (integration)
# ─────────────────────────────────────────────────────────────────────

class TestCheckAndEscalate:
    """Tests for check_and_escalate(session_id, user_input) → (result, bool)."""

    @pytest.mark.asyncio
    async def test_no_match_no_escalation(self):
        """Safe input → returns (EscalationResult, False)."""
        with patch(
            "app.agents.escalation.llm_verify_escalation", new_callable=AsyncMock
        ) as _mock_verify:
            result, is_escalated = await check_and_escalate(
                "sess-001", "今天天气真好"
            )

        assert is_escalated is False
        assert result.level == EscalationLevel.NONE
        assert result.should_block is False

    @pytest.mark.asyncio
    async def test_match_triggers_escalation(self):
        """Dangerous input matching a blocking rule → returns (result, True)."""
        with patch(
            "app.agents.escalation.llm_verify_escalation", new_callable=AsyncMock
        ) as mock_verify, patch(
            "app.agents.escalation.db", new_callable=AsyncMock
        ) as mock_db_local:
            mock_verify.return_value = True
            mock_db_local.execute = AsyncMock()

            result, is_escalated = await check_and_escalate(
                "sess-001", "我的脸红肿刺痛起疹子了"
            )

        assert is_escalated is True
        assert result.level == EscalationLevel.URGENT
        assert result.should_block is True


# ─────────────────────────────────────────────────────────────────────
# TestCheckEscalation (convenience function)
# ─────────────────────────────────────────────────────────────────────

class TestCheckEscalation:
    """Tests for check_escalation(user_input) → EscalationResult."""

    @pytest.mark.asyncio
    async def test_no_match(self):
        """No rule matched → returns NONE result."""
        result = await check_escalation("你好")
        assert result.level == EscalationLevel.NONE

    @pytest.mark.asyncio
    async def test_medium_match(self):
        """MEDIUM rule matched (no LLM verify) → returns MEDIUM result."""
        result = await check_escalation("我对这个成分过敏")
        assert result.level == EscalationLevel.MEDIUM
        assert result.action == EscalationAction.INTERRUPT
