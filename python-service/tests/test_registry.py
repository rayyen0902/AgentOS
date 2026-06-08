"""
Tests for the registry layer: tool registration dispatch and retrieve_for_agent.

The registry wraps 6 raw tool functions with retry + fallback, and provides
retrieve_for_agent() which queries different memory layers per agent type.
"""

import pytest
from unittest.mock import AsyncMock, patch

from app.tools.models import (
    FERetrieveInput,
    FERetrieveOutput,
    MemoryItem,
    FEIngestInput,
    FEIngestOutput,
    RAGSearchInput,
    RAGSearchOutput,
    KnowledgeItem,
    RAGConflictInput,
    RAGConflictOutput,
    ConflictItem,
    ProductCRUDInput,
    ProductCRUDOutput,
    ProductItem,
    ProfileQueryInput,
    ProfileQueryOutput,
)
from app.tools.registry import (
    fe_retrieve,
    fe_ingest,
    rag_search,
    rag_conflict,
    product_crud,
    profile_query,
    retrieve_for_agent,
    MemoryContext,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def no_sleep():
    with patch("asyncio.sleep", new_callable=AsyncMock):
        yield


def _mk_ferev_output(content, items=None, count=None):
    items = items or []
    return FERetrieveOutput(
        content=content,
        raw_items=items,
        retrieved_count=count if count is not None else len(items),
    )


# ===================================================================
# Registered tool dispatch — each registered function wraps the
# correct raw function
# ===================================================================


class TestFeRetrieveRegistered:
    @pytest.mark.asyncio
    async def test_fe_retrieve_wraps_raw(self, no_sleep):
        """Calling fe_retrieve dispatches to the correct raw fe_retrieve function."""
        expected = _mk_ferev_output("mem content")
        with patch("app.tools.registry._fe_retrieve_raw", new_callable=AsyncMock) as raw:
            raw.return_value = expected
            result = await fe_retrieve(
                FERetrieveInput(query="q", user_id=1, namespace="ns")
            )
        assert result == expected
        raw.assert_called_once()


class TestFeIngestRegistered:
    @pytest.mark.asyncio
    async def test_fe_ingest_wraps_raw(self, no_sleep):
        """Calling fe_ingest dispatches to the correct raw fe_ingest function."""
        expected = FEIngestOutput(msg_id="m1", success=True)
        with patch("app.tools.registry._fe_ingest_raw", new_callable=AsyncMock) as raw:
            raw.return_value = expected
            result = await fe_ingest(
                FEIngestInput(
                    text="t", role="user", session_id="s", user_id=1, namespace="ns"
                )
            )
        assert result == expected
        raw.assert_called_once()


class TestRagSearchRegistered:
    @pytest.mark.asyncio
    async def test_rag_search_wraps_raw(self, no_sleep):
        """Calling rag_search dispatches to the correct raw rag_search function."""
        expected = RAGSearchOutput(items=[
            KnowledgeItem(id=1, name="p", score=0.9),
        ], total=1)
        with patch("app.tools.registry._rag_search_raw", new_callable=AsyncMock) as raw:
            raw.return_value = expected
            result = await rag_search(RAGSearchInput(query="保湿", tenant_id=1))
        assert result.total == 1
        raw.assert_called_once()


class TestRagConflictRegistered:
    @pytest.mark.asyncio
    async def test_rag_conflict_wraps_raw(self, no_sleep):
        """Calling rag_conflict dispatches to the correct raw rag_conflict function."""
        expected = RAGConflictOutput(conflicts=[], has_urgent=False)
        with patch("app.tools.registry._rag_conflict_raw", new_callable=AsyncMock) as raw:
            raw.return_value = expected
            result = await rag_conflict(
                RAGConflictInput(ingredients=["water"], user_id=1)
            )
        assert result.has_urgent is False
        raw.assert_called_once()


class TestProductCRUDRegistered:
    @pytest.mark.asyncio
    async def test_product_crud_wraps_raw(self, no_sleep):
        """Calling product_crud dispatches to the correct raw product_crud function."""
        expected = ProductCRUDOutput(
            success=True, action="list", products=[], affected_rows=0
        )
        with patch("app.tools.registry._product_crud_raw", new_callable=AsyncMock) as raw:
            raw.return_value = expected
            result = await product_crud(ProductCRUDInput(action="list", tenant_id=1))
        assert result.success is True
        raw.assert_called_once()


class TestProfileQueryRegistered:
    @pytest.mark.asyncio
    async def test_profile_query_wraps_raw(self, no_sleep):
        """Calling profile_query dispatches to the correct raw profile_query function."""
        expected = ProfileQueryOutput(
            skin_type="油性",
            skin_concerns=["毛孔粗大"],
            allergies=[],
            current_products=[],
            profile_completeness=0.5,
        )
        with patch("app.tools.registry._profile_query_raw", new_callable=AsyncMock) as raw:
            raw.return_value = expected
            result = await profile_query(ProfileQueryInput(user_id=1))
        assert result.skin_type == "油性"
        raw.assert_called_once()


# ===================================================================
# TestRetrieveForAgent — agent-type dispatch per Step 5 5.10
# ===================================================================


class TestRetrieveForAgent:
    @pytest.mark.asyncio
    async def test_workshop_gets_semantic_preference_episodic(self, no_sleep):
        """agent_type="workshop" → semantic(n=5) + preference(n=5) + episodic(n=3)."""
        sem = _mk_ferev_output("[semantic]", [MemoryItem(id="s1", text="sem", layer="semantic", score=0.9)], 1)
        pref = _mk_ferev_output("[preference]", [MemoryItem(id="p1", text="pref", layer="preference", score=0.8)], 1)
        epi = _mk_ferev_output("[episodic]", [MemoryItem(id="e1", text="ep", layer="episodic", score=0.7)], 1)

        with patch("app.tools.registry._fe_retrieve_raw", new_callable=AsyncMock) as raw:
            raw.side_effect = [sem, pref, epi]
            ctx = await retrieve_for_agent(
                query="保湿", user_id=1, namespace="tenant:1:agent:workshop", agent_type="workshop"
            )

        assert isinstance(ctx, MemoryContext)
        # semantic
        assert ctx.semantic.content == "[semantic]"
        assert ctx.semantic.retrieved_count == 1
        # preference
        assert ctx.preference.content == "[preference]"
        # episodic
        assert ctx.episodic.content == "[episodic]"
        assert ctx.episodic.retrieved_count == 1

        # Verify n values passed into the raw calls
        call_args_list = raw.call_args_list
        assert call_args_list[0].args[0].n == 5   # semantic
        assert call_args_list[0].args[0].layer == "semantic"
        assert call_args_list[1].args[0].n == 5   # preference
        assert call_args_list[1].args[0].layer == "preference"
        assert call_args_list[2].args[0].n == 3   # episodic
        assert call_args_list[2].args[0].layer == "episodic"

    @pytest.mark.asyncio
    async def test_diagnosis_gets_semantic_episodic(self, no_sleep):
        """agent_type="diagnosis" → semantic(n=5) + episodic(n=5), preference empty."""
        sem = _mk_ferev_output("[semantic]", [MemoryItem(id="s1", text="sem", layer="semantic", score=0.9)], 1)
        epi = _mk_ferev_output("[episodic]", [MemoryItem(id="e1", text="ep", layer="episodic", score=0.7)], 1)

        with patch("app.tools.registry._fe_retrieve_raw", new_callable=AsyncMock) as raw:
            raw.side_effect = [sem, epi]
            ctx = await retrieve_for_agent(
                query="测试", user_id=1, namespace="tenant:1:agent:diagnosis", agent_type="diagnosis"
            )

        assert ctx.semantic.content == "[semantic]"
        assert ctx.preference.content == ""
        assert ctx.preference.retrieved_count == 0
        assert ctx.episodic.content == "[episodic]"

        call_args_list = raw.call_args_list
        assert call_args_list[0].args[0].n == 5  # semantic
        assert call_args_list[1].args[0].n == 5  # episodic
        assert call_args_list[1].args[0].layer == "episodic"

    @pytest.mark.asyncio
    async def test_front_gets_semantic_episodic(self, no_sleep):
        """agent_type="front" → semantic(n=5) + episodic(n=5), preference empty."""
        sem = _mk_ferev_output("[semantic]")
        epi = _mk_ferev_output("[episodic]")

        with patch("app.tools.registry._fe_retrieve_raw", new_callable=AsyncMock) as raw:
            raw.side_effect = [sem, epi]
            ctx = await retrieve_for_agent(
                query="你好", user_id=1, namespace="tenant:1:agent:front", agent_type="front"
            )

        assert ctx.semantic.content == "[semantic]"
        assert ctx.preference.content == ""
        assert ctx.episodic.content == "[episodic]"
        # front falls into the same (diagnosis, front) branch
        assert raw.call_count == 2

    @pytest.mark.asyncio
    async def test_default_gets_semantic_only(self, no_sleep):
        """Unknown agent_type → single semantic call with layer="all", n=5."""
        sem = _mk_ferev_output("[semantic all]", [MemoryItem(id="s1", text="sem", layer="semantic", score=0.9)], 1)

        with patch("app.tools.registry._fe_retrieve_raw", new_callable=AsyncMock) as raw:
            raw.return_value = sem
            ctx = await retrieve_for_agent(
                query="保湿", user_id=1, namespace="tenant:1:agent:unknown", agent_type="unknown"
            )

        assert ctx.semantic.content == "[semantic all]"
        assert ctx.preference.content == ""
        assert ctx.preference.retrieved_count == 0
        assert ctx.episodic.content == ""
        assert ctx.episodic.retrieved_count == 0
        raw.assert_called_once()
        call_arg = raw.call_args_list[0].args[0]
        assert call_arg.layer == "all"
        assert call_arg.n == 5
