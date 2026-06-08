package session

import (
	"context"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/stretchr/testify/assert"

	"github.com/agentos/go-service/internal/model"
	redisutil "github.com/agentos/go-service/internal/redis"
)

// newTestManager creates a Manager backed by an in-memory miniredis instance.
func newTestManager(t *testing.T) (*Manager, *miniredis.Miniredis) {
	t.Helper()
	mr := miniredis.RunT(t)

	// redisutil.New does a Ping, which works with miniredis.
	client, err := redisutil.New(mr.Addr())
	assert.NoError(t, err)

	t.Cleanup(func() {
		client.Close()
	})

	return NewManager(client), mr
}

func TestNewManager(t *testing.T) {
	mgr, _ := newTestManager(t)
	assert.NotNil(t, mgr)
}

func TestCreate(t *testing.T) {
	mgr, _ := newTestManager(t)
	ctx := context.Background()

	state, err := mgr.Create(ctx, "test-session-1", 100, 1, "wecom")
	assert.NoError(t, err)
	assert.NotNil(t, state)
	assert.Equal(t, "test-session-1", state.SessionID)
	assert.Equal(t, 1800, state.TTLSeconds)
	assert.Equal(t, model.StageIdle, state.Stage)
	assert.False(t, state.CreatedAt.IsZero())
}

func TestGet(t *testing.T) {
	mgr, _ := newTestManager(t)
	ctx := context.Background()

	created, err := mgr.Create(ctx, "test-session-2", 200, 2, "xhs")
	assert.NoError(t, err)

	got, err := mgr.Get(ctx, "test-session-2")
	assert.NoError(t, err)
	assert.Equal(t, created.SessionID, got.SessionID)
	assert.Equal(t, created.Stage, got.Stage)
	assert.Equal(t, created.TTLSeconds, got.TTLSeconds)
}

func TestGetNotFound(t *testing.T) {
	mgr, _ := newTestManager(t)
	ctx := context.Background()

	state, err := mgr.Get(ctx, "nonexistent")
	assert.Error(t, err)
	assert.Nil(t, state)
}

func TestSet(t *testing.T) {
	mgr, _ := newTestManager(t)
	ctx := context.Background()

	state, err := mgr.Create(ctx, "test-session-3", 300, 3, "douyin")
	assert.NoError(t, err)

	// Modify Stage and persist
	state.Stage = model.StageAgentRunning
	err = mgr.Set(ctx, state)
	assert.NoError(t, err)

	// Re-read and verify
	got, err := mgr.Get(ctx, "test-session-3")
	assert.NoError(t, err)
	assert.Equal(t, model.StageAgentRunning, got.Stage)
}

func TestSetWithCustomTTL(t *testing.T) {
	mgr, mr := newTestManager(t)
	ctx := context.Background()

	sessionID := "test-session-ttl"
	state, err := mgr.Create(ctx, sessionID, 1, 1, "test")
	assert.NoError(t, err)

	// Set a custom TTL of 60 seconds
	state.TTLSeconds = 60
	err = mgr.Set(ctx, state)
	assert.NoError(t, err)

	// Verify the key has a TTL set (approximately 60 seconds)
	key := "agentos:session:" + sessionID
	ttl := mr.TTL(key)
	assert.Greater(t, ttl, time.Duration(0), "TTL should be positive")
	assert.LessOrEqual(t, ttl, 60*time.Second, "TTL should be <= 60s")
}

func TestDelete(t *testing.T) {
	mgr, _ := newTestManager(t)
	ctx := context.Background()

	_, err := mgr.Create(ctx, "test-session-4", 400, 4, "wecom")
	assert.NoError(t, err)

	err = mgr.Delete(ctx, "test-session-4")
	assert.NoError(t, err)

	_, err = mgr.Get(ctx, "test-session-4")
	assert.Error(t, err)
}

func TestExists(t *testing.T) {
	mgr, _ := newTestManager(t)
	ctx := context.Background()

	// Non-existent
	exists, err := mgr.Exists(ctx, "nonexistent")
	assert.NoError(t, err)
	assert.False(t, exists)

	// Create then check
	_, err = mgr.Create(ctx, "test-session-5", 500, 5, "xhs")
	assert.NoError(t, err)

	exists, err = mgr.Exists(ctx, "test-session-5")
	assert.NoError(t, err)
	assert.True(t, exists)
}

func TestAcquireLock(t *testing.T) {
	mgr, _ := newTestManager(t)
	ctx := context.Background()

	sessionID := "test-lock-1"
	ttl := 10 * time.Second

	// First acquire should succeed
	ok, err := mgr.AcquireLock(ctx, sessionID, ttl)
	assert.NoError(t, err)
	assert.True(t, ok)

	// Second acquire on same key should fail (SetNX)
	ok, err = mgr.AcquireLock(ctx, sessionID, ttl)
	assert.NoError(t, err)
	assert.False(t, ok)
}

func TestReleaseLock(t *testing.T) {
	mgr, _ := newTestManager(t)
	ctx := context.Background()

	sessionID := "test-lock-2"
	ttl := 10 * time.Second

	// Acquire
	ok, err := mgr.AcquireLock(ctx, sessionID, ttl)
	assert.NoError(t, err)
	assert.True(t, ok)

	// Release
	err = mgr.ReleaseLock(ctx, sessionID)
	assert.NoError(t, err)

	// Acquire again — should succeed
	ok, err = mgr.AcquireLock(ctx, sessionID, ttl)
	assert.NoError(t, err)
	assert.True(t, ok)
}

func TestPublishSSE(t *testing.T) {
	mgr, mr := newTestManager(t)
	ctx := context.Background()

	sessionID := "test-sse-1"
	data := map[string]string{"message": "hello"}

	err := mgr.PublishSSE(ctx, sessionID, "agent_response", data)
	assert.NoError(t, err)

	// Verify the stream has entries
	streamKey := "agentos:sse_channel:" + sessionID
	entries, err := mr.Stream(streamKey)
	assert.NoError(t, err)
	assert.NotEmpty(t, entries, "stream should have at least one entry")

	// Verify stream key has TTL set
	ttl := mr.TTL(streamKey)
	assert.Greater(t, ttl, time.Duration(0), "stream TTL should be positive")
	assert.LessOrEqual(t, ttl, 60*time.Minute, "stream TTL should be <= 60m")
}

func TestPublishSSENoSession(t *testing.T) {
	mgr, mr := newTestManager(t)
	ctx := context.Background()

	sessionID := "test-sse-no-session"
	data := map[string]string{"message": "no session"}

	// Publish to a session that was never created — should not panic
	err := mgr.PublishSSE(ctx, sessionID, "agent_response", data)
	assert.NoError(t, err)

	// Data should still be written to the stream (stream auto-created)
	streamKey := "agentos:sse_channel:" + sessionID
	entries, err := mr.Stream(streamKey)
	assert.NoError(t, err)
	assert.NotEmpty(t, entries, "stream should have entries even without a prior Create")
}
