"""
Tests for the 6 tool wrapper functions in app.tools.registry.

Each wrapper delegates to a raw function via with_retry (exponential backoff)
and applies a fallback when all retries are exhausted.  These tests verify:

  1. Successful call returns the correct output type
  2. First failure → retry succeeds
  3. All retries exhausted → returns fallback (NEVER an exception)
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
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _mk_memory(id="m1", text="memory", layer="semantic", score=0.9):
    return MemoryItem(id=id, text=text, layer=layer, score=score)


@pytest.fixture
def no_sleep():
    """Skip asyncio.sleep so exponential-backoff delays do not slow down tests."""
    with patch("asyncio.sleep", new_callable=AsyncMock):
        yield


# ===================================================================
# TestFeRetrieve  (max_retries=2, delay=0.5 s)
# ===================================================================


class TestFeRetrieve:
    @pytest.mark.asyncio
    async def test_success(self, no_sleep):
        """Mock raw returns valid data → registry returns parsed FERetrieveOutput."""
        expected = FERetrieveOutput(
            content="[semantic] test memory",
            raw_items=[_mk_memory()],
            retrieved_count=1,
        )
        with patch("app.tools.registry._fe_retrieve_raw", new_callable=AsyncMock) as raw:
            raw.return_value = expected
            result = await fe_retrieve(
                FERetrieveInput(query="test", user_id=1, namespace="tenant:1:agent:front")
            )
        assert result == expected
        raw.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_then_success(self, no_sleep):
        """First call fails, second call succeeds → returns correct output."""
        expected = FERetrieveOutput(
            content="[semantic] ok",
            raw_items=[_mk_memory(text="ok")],
            retrieved_count=1,
        )
        with patch("app.tools.registry._fe_retrieve_raw", new_callable=AsyncMock) as raw:
            raw.side_effect = [Exception("gRPC timeout"), expected]
            result = await fe_retrieve(
                FERetrieveInput(query="test", user_id=1, namespace="ns")
            )
        assert result == expected
        assert raw.call_count == 2

    @pytest.mark.asyncio
    async def test_all_retries_exhausted(self, no_sleep):
        """All 3 attempts fail → returns empty FERetrieveOutput (no exception)."""
        with patch("app.tools.registry._fe_retrieve_raw", new_callable=AsyncMock) as raw:
            raw.side_effect = Exception("always fails")
            result = await fe_retrieve(
                FERetrieveInput(query="test", user_id=1, namespace="ns")
            )
        assert isinstance(result, FERetrieveOutput)
        assert result.content == ""
        assert result.retrieved_count == 0
        assert result.raw_items == []
        assert raw.call_count == 3  # max_retries=2 → 3 total attempts


# ===================================================================
# TestFeIngest  (max_retries=3, delay=1.0 s)
# ===================================================================


class TestFeIngest:
    @pytest.mark.asyncio
    async def test_success(self, no_sleep):
        """Mock raw → returns FEIngestOutput with success=True."""
        expected = FEIngestOutput(msg_id="msg-001", success=True)
        with patch("app.tools.registry._fe_ingest_raw", new_callable=AsyncMock) as raw:
            raw.return_value = expected
            result = await fe_ingest(
                FEIngestInput(
                    text="hello",
                    role="user",
                    session_id="s1",
                    user_id=1,
                    namespace="ns",
                )
            )
        assert result == expected
        raw.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback(self, no_sleep):
        """All 4 attempts fail → returns FEIngestOutput(success=False) (non-blocking)."""
        with patch("app.tools.registry._fe_ingest_raw", new_callable=AsyncMock) as raw:
            raw.side_effect = Exception("FE down")
            result = await fe_ingest(
                FEIngestInput(
                    text="hello",
                    role="user",
                    session_id="s1",
                    user_id=1,
                    namespace="ns",
                )
            )
        assert isinstance(result, FEIngestOutput)
        assert result.success is False
        assert raw.call_count == 4  # max_retries=3 → 4 total attempts


# ===================================================================
# TestRagSearch  (max_retries=2, delay=0.5 s)
# ===================================================================


class TestRagSearch:
    @pytest.mark.asyncio
    async def test_success(self, no_sleep):
        """Mock raw returns items → RAGSearchOutput with items and total."""
        expected = RAGSearchOutput(
            items=[
                KnowledgeItem(id=1, name="product-a", score=0.95),
                KnowledgeItem(id=2, name="product-b", score=0.80),
            ],
            total=2,
        )
        with patch("app.tools.registry._rag_search_raw", new_callable=AsyncMock) as raw:
            raw.return_value = expected
            result = await rag_search(
                RAGSearchInput(query="保湿霜", tenant_id=1, top_k=5)
            )
        assert result == expected
        assert result.total == 2
        raw.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_result(self, no_sleep):
        """No matching rows → empty items list."""
        expected = RAGSearchOutput(items=[], total=0)
        with patch("app.tools.registry._rag_search_raw", new_callable=AsyncMock) as raw:
            raw.return_value = expected
            result = await rag_search(
                RAGSearchInput(query="nonexistent", tenant_id=1)
            )
        assert result.items == []
        assert result.total == 0

    @pytest.mark.asyncio
    async def test_fallback(self, no_sleep):
        """All retries fail → empty RAGSearchOutput."""
        with patch("app.tools.registry._rag_search_raw", new_callable=AsyncMock) as raw:
            raw.side_effect = Exception("DB error")
            result = await rag_search(
                RAGSearchInput(query="test", tenant_id=1)
            )
        assert isinstance(result, RAGSearchOutput)
        assert result.items == []
        assert result.total == 0
        assert raw.call_count == 3


# ===================================================================
# TestRagConflict  (max_retries=2, delay=0.5 s)
# ===================================================================


class TestRagConflict:
    @pytest.mark.asyncio
    async def test_success(self, no_sleep):
        """Mock raw returns conflicts with has_urgent=True."""
        expected = RAGConflictOutput(
            conflicts=[
                ConflictItem(
                    conflict_type="ingredient_conflict",
                    severity="high",
                    description="A 与 B 冲突",
                    ingredients_involved=["retinol", "vitamin_c"],
                    suggestion="避免同时使用",
                )
            ],
            has_urgent=True,
        )
        with patch("app.tools.registry._rag_conflict_raw", new_callable=AsyncMock) as raw:
            raw.return_value = expected
            result = await rag_conflict(
                RAGConflictInput(
                    ingredients=["retinol", "vitamin_c"],
                    user_id=1,
                    check_types=["ingredient_conflict"],
                )
            )
        assert result.has_urgent is True
        assert len(result.conflicts) == 1
        raw.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_conflict(self, no_sleep):
        """No conflicts found → has_urgent=False, empty conflicts."""
        expected = RAGConflictOutput(conflicts=[], has_urgent=False)
        with patch("app.tools.registry._rag_conflict_raw", new_callable=AsyncMock) as raw:
            raw.return_value = expected
            result = await rag_conflict(
                RAGConflictInput(ingredients=["water"], user_id=1)
            )
        assert result.has_urgent is False
        assert result.conflicts == []

    @pytest.mark.asyncio
    async def test_fallback(self, no_sleep):
        """DB error → has_urgent=False (conservative, does not block recommendation)."""
        with patch("app.tools.registry._rag_conflict_raw", new_callable=AsyncMock) as raw:
            raw.side_effect = Exception("DB error")
            result = await rag_conflict(
                RAGConflictInput(ingredients=["water"], user_id=1)
            )
        assert isinstance(result, RAGConflictOutput)
        assert result.has_urgent is False
        assert result.conflicts == []
        assert raw.call_count == 3


# ===================================================================
# TestProductCRUD  (max_retries=1, delay=0.0 s)
# ===================================================================


class TestProductCRUD:
    @pytest.mark.asyncio
    async def test_create(self, no_sleep):
        """action=create → raw returns ProductCRUDOutput with success=True."""
        expected = ProductCRUDOutput(
            success=True,
            action="create",
            products=[
                ProductItem(id=1, name="保湿霜", brand="A", category="保湿")
            ],
            affected_rows=1,
        )
        with patch("app.tools.registry._product_crud_raw", new_callable=AsyncMock) as raw:
            raw.return_value = expected
            result = await product_crud(
                ProductCRUDInput(
                    action="create",
                    tenant_id=1,
                    data={"name": "保湿霜", "brand": "A"},
                )
            )
        assert result.success is True
        assert result.action == "create"
        assert result.affected_rows == 1
        raw.assert_called_once()

    @pytest.mark.asyncio
    async def test_read(self, no_sleep):
        """action=read → raw returns ProductCRUDOutput with product data."""
        expected = ProductCRUDOutput(
            success=True,
            action="read",
            products=[ProductItem(id=1, name="保湿霜", brand="A")],
            affected_rows=1,
        )
        with patch("app.tools.registry._product_crud_raw", new_callable=AsyncMock) as raw:
            raw.return_value = expected
            result = await product_crud(
                ProductCRUDInput(action="read", tenant_id=1, product_id=1)
            )
        assert result.success is True
        assert result.products[0].name == "保湿霜"

    @pytest.mark.asyncio
    async def test_list(self, no_sleep):
        """action=list → raw returns ProductCRUDOutput with items array."""
        expected = ProductCRUDOutput(
            success=True,
            action="list",
            products=[
                ProductItem(id=1, name="a"),
                ProductItem(id=2, name="b"),
            ],
            affected_rows=2,
        )
        with patch("app.tools.registry._product_crud_raw", new_callable=AsyncMock) as raw:
            raw.return_value = expected
            result = await product_crud(
                ProductCRUDInput(action="list", tenant_id=1)
            )
        assert len(result.products) == 2
        assert result.affected_rows == 2

    @pytest.mark.asyncio
    async def test_search(self, no_sleep):
        """action=search → raw returns ProductCRUDOutput."""
        expected = ProductCRUDOutput(
            success=True,
            action="search",
            products=[ProductItem(id=1, name="美白精华")],
            affected_rows=1,
        )
        with patch("app.tools.registry._product_crud_raw", new_callable=AsyncMock) as raw:
            raw.return_value = expected
            result = await product_crud(
                ProductCRUDInput(action="search", tenant_id=1, query="美白")
            )
        assert result.success is True
        assert result.action == "search"

    @pytest.mark.asyncio
    async def test_fallback(self, no_sleep):
        """DB error → ProductCRUDOutput(success=False, error=...)."""
        with patch("app.tools.registry._product_crud_raw", new_callable=AsyncMock) as raw:
            raw.side_effect = Exception("DB error")
            result = await product_crud(
                ProductCRUDInput(action="list", tenant_id=1)
            )
        assert isinstance(result, ProductCRUDOutput)
        assert result.success is False
        assert "Product CRUD failed after retries" in result.error
        assert raw.call_count == 2  # max_retries=1 → 2 attempts


# ===================================================================
# TestProfileQuery  (max_retries=2, delay=0.5 s)
# ===================================================================


class TestProfileQuery:
    @pytest.mark.asyncio
    async def test_success(self, no_sleep):
        """Mock raw returns user profile → ProfileQueryOutput with data."""
        expected = ProfileQueryOutput(
            skin_type="干性",
            skin_concerns=["干燥", "细纹"],
            allergies=["酒精"],
            current_products=[{"name": "保湿霜", "brand": "A"}],
            profile_completeness=1.0,
        )
        with patch("app.tools.registry._profile_query_raw", new_callable=AsyncMock) as raw:
            raw.return_value = expected
            result = await profile_query(
                ProfileQueryInput(user_id=1, include=["skin_type", "concerns", "allergies", "current_products"])
            )
        assert result.skin_type == "干性"
        assert result.profile_completeness == 1.0
        raw.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_profile(self, no_sleep):
        """No user found → ProfileQueryOutput with default/empty values."""
        expected = ProfileQueryOutput(
            skin_type=None,
            skin_concerns=[],
            allergies=[],
            current_products=[],
            profile_completeness=0.0,
        )
        with patch("app.tools.registry._profile_query_raw", new_callable=AsyncMock) as raw:
            raw.return_value = expected
            result = await profile_query(
                ProfileQueryInput(user_id=999)
            )
        assert result.skin_type is None
        assert result.profile_completeness == 0.0

    @pytest.mark.asyncio
    async def test_fallback(self, no_sleep):
        """DB error → empty profile (no exception)."""
        with patch("app.tools.registry._profile_query_raw", new_callable=AsyncMock) as raw:
            raw.side_effect = Exception("DB error")
            result = await profile_query(
                ProfileQueryInput(user_id=1)
            )
        assert isinstance(result, ProfileQueryOutput)
        assert result.skin_type is None
        assert result.skin_concerns == []
        assert result.allergies == []
        assert result.current_products == []
        assert result.profile_completeness == 0.0
        assert raw.call_count == 3
