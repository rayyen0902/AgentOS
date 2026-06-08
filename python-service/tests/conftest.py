import pytest
from unittest.mock import AsyncMock, patch

from app.agents.base import SessionContext, AgentResult


@pytest.fixture
def sample_session_ctx():
    """Standard SessionContext for tests."""
    return SessionContext(
        session_id="test-session-001",
        user_id=1,
        tenant_id=1,
        platform="test",
        input="你好",
        agent_state={"stage": "idle"},
    )


@pytest.fixture
def mock_llm():
    """Mock the llm_chat function used by all agents."""
    with patch("app.agents.llm_util.llm_chat", new_callable=AsyncMock) as mock:
        mock.return_value = '{"intent": "chat", "reply": "mock reply"}'
        yield mock


@pytest.fixture
def mock_db():
    """Mock the database pool (db_util.Database instance)."""
    with patch("db_util.db", new_callable=AsyncMock) as mock:
        mock.fetchrow = AsyncMock()
        mock.fetch = AsyncMock()
        mock.execute = AsyncMock()
        mock.fetchval = AsyncMock()
        yield mock


@pytest.fixture
def mock_redis():
    """Mock the Redis client (redis_util.RedisClient instance)."""
    with patch("redis_util.redis_client", new_callable=AsyncMock) as mock:
        mock.get = AsyncMock(return_value=None)
        mock.set = AsyncMock()
        mock.set_json = AsyncMock()
        mock.get_json = AsyncMock(return_value=None)
        mock.delete = AsyncMock()
        mock.exists = AsyncMock(return_value=False)
        yield mock
