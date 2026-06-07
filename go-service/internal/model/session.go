package model

import "time"

type Stage string

const (
	StageIdle           Stage = "idle"
	StageAgentRunning   Stage = "agent_running"
	StageAgentInterrupted Stage = "agent_interrupted"
	StageEscalated      Stage = "escalated"
	StageError          Stage = "error"
)

type InterruptRequest struct {
	InterruptID string        `json:"interrupt_id"`
	Label       string        `json:"label"`
	Question    string        `json:"question"`
	Options     []string      `json:"options"`
	TimeoutS    int           `json:"timeout_s"`
	CreatedAt   time.Time     `json:"created_at"`
}

type StatusEvent struct {
	Seq    int    `json:"seq"`
	Source string `json:"source"`
	Status string `json:"status"`
	Label  string `json:"label"`
}

type SessionState struct {
	SessionID    string          `json:"session_id"`
	Stage        Stage           `json:"stage"`
	CurrentAgent *string         `json:"current_agent"`
	AgentState   interface{}     `json:"agent_state"`
	Interrupt    *InterruptRequest `json:"interrupt"`
	StatusStream []StatusEvent   `json:"status_stream"`
	ErrorInfo    interface{}     `json:"error_info"`
	UserID       int64           `json:"user_id"`
	TenantID     int64           `json:"tenant_id"`
	Platform     string          `json:"platform"`
	CreatedAt    time.Time       `json:"created_at"`
	UpdatedAt    time.Time       `json:"updated_at"`
	TTLSeconds   int             `json:"ttl_seconds"`
}
