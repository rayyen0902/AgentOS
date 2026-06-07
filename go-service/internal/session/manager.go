package session

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/agentos/go-service/internal/model"
	redisutil "github.com/agentos/go-service/internal/redis"
)

const (
	sessionKeyPrefix   = "session:"
	sseChannelPrefix   = "sse_channel:"
	agentLockPrefix    = "agent_lock:"
	defaultTTL         = 30 * time.Minute
	sseChannelTTL      = 60 * time.Minute
)

type Manager struct {
	redis *redisutil.Client
}

func NewManager(r *redisutil.Client) *Manager {
	return &Manager{redis: r}
}

func sessionKey(sessionID string) string    { return sessionKeyPrefix + sessionID }
func sseChannelKey(sessionID string) string { return sseChannelPrefix + sessionID }
func agentLockKey(sessionID string) string  { return agentLockPrefix + sessionID }

func (m *Manager) Get(ctx context.Context, sessionID string) (*model.SessionState, error) {
	var state model.SessionState
	if err := m.redis.GetJSON(ctx, sessionKey(sessionID), &state); err != nil {
		return nil, fmt.Errorf("session get: %w", err)
	}
	return &state, nil
}

func (m *Manager) Set(ctx context.Context, state *model.SessionState) error {
	state.UpdatedAt = time.Now()
	return m.redis.SetJSON(ctx, sessionKey(state.SessionID), state, defaultTTL)
}

func (m *Manager) Delete(ctx context.Context, sessionID string) error {
	return m.redis.Delete(ctx, sessionKey(sessionID))
}

func (m *Manager) Exists(ctx context.Context, sessionID string) (bool, error) {
	return m.redis.Exists(ctx, sessionKey(sessionID))
}

func (m *Manager) Create(ctx context.Context, sessionID string, userID, tenantID int64, platform string) (*model.SessionState, error) {
	now := time.Now()
	state := &model.SessionState{
		SessionID:    sessionID,
		Stage:        model.StageIdle,
		CurrentAgent: nil,
		AgentState:   nil,
		Interrupt:    nil,
		StatusStream: []model.StatusEvent{},
		ErrorInfo:    nil,
		UserID:       userID,
		TenantID:     tenantID,
		Platform:     platform,
		CreatedAt:    now,
		UpdatedAt:    now,
		TTLSeconds:   1800,
	}
	if err := m.Set(ctx, state); err != nil {
		return nil, err
	}
	return state, nil
}

// AcquireLock tries to acquire distributed lock for the session. Returns true if acquired.
func (m *Manager) AcquireLock(ctx context.Context, sessionID string, ttl time.Duration) (bool, error) {
	return m.redis.Lock(ctx, agentLockKey(sessionID), ttl)
}

func (m *Manager) ReleaseLock(ctx context.Context, sessionID string) error {
	return m.redis.Unlock(ctx, agentLockKey(sessionID))
}

// PublishSSE writes an event to the SSE Redis Stream.
func (m *Manager) PublishSSE(ctx context.Context, sessionID string, eventType string, data interface{}) error {
	payload, err := json.Marshal(data)
	if err != nil {
		return fmt.Errorf("marshal sse data: %w", err)
	}
	return m.redis.XAdd(ctx, sseChannelKey(sessionID), map[string]interface{}{
		"event": eventType,
		"data":  string(payload),
	})
}
