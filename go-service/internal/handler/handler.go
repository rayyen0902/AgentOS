package handler

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/http"
	"strconv"
	"time"

	"github.com/agentos/go-service/internal/middleware"
	"github.com/agentos/go-service/internal/model"
	"github.com/agentos/go-service/internal/session"
)

func Health(w http.ResponseWriter, r *http.Request) {
	middleware.WriteJSON(w, 0, model.NewSuccessResponse(map[string]string{"status": "ok"}, middleware.GetTraceID(r.Context())))
}

// Auth stubs — return placeholder responses.
// TODO(Step 4): Implement real phone login/signup flow (Register/Login/SendCode).

// TODO(Step 4): Implement real phone registration with SMS verification.
func Register(w http.ResponseWriter, r *http.Request) {
	middleware.WriteJSON(w, 0, model.NewSuccessResponse(map[string]string{"message": "register ok"}, middleware.GetTraceID(r.Context())))
}

// TODO(Step 4): Implement real login with JWT token issuance.
func Login(w http.ResponseWriter, r *http.Request) {
	middleware.WriteJSON(w, 0, model.NewSuccessResponse(map[string]string{"token": "placeholder-jwt-token"}, middleware.GetTraceID(r.Context())))
}

// TODO(Step 4): Implement real SMS verification code delivery.
func SendCode(w http.ResponseWriter, r *http.Request) {
	middleware.WriteJSON(w, 0, model.NewSuccessResponse(map[string]string{"message": "code sent"}, middleware.GetTraceID(r.Context())))
}

// Admin stubs — all are Step 4 scope.
// TODO(Step 4): Implement real tenant management (ListTenants/ApproveTenant/GetTenant).
func ListTenants(w http.ResponseWriter, r *http.Request) {
	middleware.WriteJSON(w, 0, model.NewSuccessResponse([]map[string]interface{}{}, middleware.GetTraceID(r.Context())))
}

func ApproveTenant(w http.ResponseWriter, r *http.Request) {
	middleware.WriteJSON(w, 0, model.NewSuccessResponse(map[string]string{"status": "approved"}, middleware.GetTraceID(r.Context())))
}

func GetTenant(w http.ResponseWriter, r *http.Request) {
	middleware.WriteJSON(w, 0, model.NewSuccessResponse(map[string]interface{}{}, middleware.GetTraceID(r.Context())))
}

// ── Step 6 ChatMessage — full concurrency control + session state ──

// ChatMessage handles POST /api/v1/chat/message
// Implements Step 6 6.1 concurrency control:
// - Acquires agent_lock:{session_id} per-session
// - Checks stage: agent_running → discard, agent_interrupted → resume
func (h *Handler) ChatMessage(w http.ResponseWriter, r *http.Request) {
	traceID := middleware.GetTraceID(r.Context())
	ctx := r.Context()

	// Limit request body to 1MB to prevent OOM DoS
	const maxBodySize = 1 << 20
	r.Body = http.MaxBytesReader(w, r.Body, maxBodySize)

	var body struct {
		SessionID string `json:"session_id"`
		Text      string `json:"text"`
		Platform  string `json:"platform"`
		UserID    string `json:"user_id"`
		TenantID  string `json:"tenant_id"`
		ImageURL  string `json:"image_url,omitempty"`
		ImageSize int64  `json:"image_size,omitempty"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		var maxBytesErr *http.MaxBytesError
		if errors.As(err, &maxBytesErr) {
			middleware.WriteJSON(w, model.CodeBadRequest,
				model.NewErrorResponse(model.CodeBadRequest, fmt.Sprintf("request body too large (max %d bytes)", maxBodySize), traceID))
			return
		}
		middleware.WriteJSON(w, model.CodeBadRequest,
			model.NewErrorResponse(model.CodeBadRequest, fmt.Sprintf("invalid request body: %v", err), traceID))
		return
	}
	if body.Text == "" {
		middleware.WriteJSON(w, model.CodeBadRequest,
			model.NewErrorResponse(model.CodeBadRequest, "text is required", traceID))
		return
	}

	if body.SessionID == "" {
		middleware.WriteJSON(w, model.CodeBadRequest,
			model.NewErrorResponse(model.CodeBadRequest, "session_id is required", traceID))
		return
	}

	// ── Step 6 6.1: Acquire per-session lock ──
	locked, lockErr := h.Session.AcquireLock(ctx, body.SessionID, 30*time.Second)
	if lockErr != nil {
		log.Printf("[WARN] agent_lock acquire error session=%s: %v (degraded — continuing without lock)", body.SessionID, lockErr)
		// Redis 不可用 → 降级继续，不阻塞请求 (6.6 系统故障边界)
	}
	if lockErr == nil && !locked {
		// Lock held by another process — treat as agent_running
		middleware.WriteJSON(w, 0,
			model.NewSuccessResponse(map[string]interface{}{
				"session_id": body.SessionID,
				"events": []map[string]interface{}{
					{"type": "reply", "data": map[string]string{"text": "正在处理上一条消息，稍等~"}},
					{"type": "done", "data": map[string]interface{}{}},
				},
				"new_agent_state": map[string]interface{}{"phase": "busy"},
				"interrupt":       nil,
				"error":           nil,
			}, traceID))
		return
	}
	defer func() {
		if locked {
			if relErr := h.Session.ReleaseLock(ctx, body.SessionID); relErr != nil {
				log.Printf("[WARN] agent_lock release error session=%s: %v", body.SessionID, relErr)
			}
		}
	}()

	// ── Load or create session state ──
	state, err := h.Session.Get(ctx, body.SessionID)
	if err != nil && !errors.Is(err, session.ErrSessionNotFound) {
		// Redis connectivity issue or other real error — do not mask it
		log.Printf("[ERROR] session get: %v", err)
		middleware.WriteJSON(w, model.CodePythonDown,
			model.NewErrorResponse(model.CodePythonDown, "session service unavailable", traceID))
		return
	}
	if errors.Is(err, session.ErrSessionNotFound) || state == nil {
		// Session not in Redis → create
		userID, err2 := strconv.ParseInt(body.UserID, 10, 64)
		if err2 != nil {
			middleware.WriteJSON(w, model.CodeBadRequest,
				model.NewErrorResponse(model.CodeBadRequest, "invalid user_id", traceID))
			return
		}
		tenantID, err2 := strconv.ParseInt(body.TenantID, 10, 64)
		if err2 != nil {
			middleware.WriteJSON(w, model.CodeBadRequest,
				model.NewErrorResponse(model.CodeBadRequest, "invalid tenant_id", traceID))
			return
		}
		state, err = h.Session.Create(ctx, body.SessionID, userID, tenantID, body.Platform)
		if err != nil {
			log.Printf("[ERROR] session create: %v", err)
			middleware.WriteJSON(w, model.CodePythonDown,
				model.NewErrorResponse(model.CodePythonDown, "session init failed", traceID))
			return
		}
	}

	// ── Stage check (6.1) ──
	if state.Stage == model.StageAgentRunning {
		// Agent is running — discard this message
		middleware.WriteJSON(w, 0,
			model.NewSuccessResponse(map[string]interface{}{
				"session_id": body.SessionID,
				"events": []map[string]interface{}{
					{"type": "reply", "data": map[string]string{"text": "正在处理上一条消息，稍等~"}},
					{"type": "done", "data": map[string]interface{}{}},
				},
				"new_agent_state": map[string]interface{}{"phase": "busy"},
				"interrupt":       nil,
				"error":           nil,
			}, traceID))
		return
	}

	if state.Stage == model.StageAgentInterrupted {
		// Interrupted → route to resume
		resp, err := h.handleResume(ctx, body.SessionID, body.Text, state)
		if err != nil {
			log.Printf("[ERROR] agent resume: %v", err)
			middleware.WriteJSON(w, model.CodePythonDown,
				model.NewErrorResponse(model.CodePythonDown, "agent resume failed", traceID))
			return
		}
		// Update session state after resume
		h.updateSessionFromResponse(ctx, state, resp)
		middleware.WriteJSON(w, 0, model.NewSuccessResponse(resp, traceID))
		return
	}

	// ── Normal flow: forward to Python orchestrator ──
	// Update stage to agent_running before forwarding
	state.Stage = model.StageAgentRunning
	agentStateJSON := serializeAgentState(state.AgentState)
	if err := h.Session.Set(ctx, state); err != nil {
		log.Printf("[WARN] session set before run: %v", err)
	}

	reqBody := map[string]interface{}{
		"session_id": body.SessionID,
		"user_id":    body.UserID,
		"tenant_id":  body.TenantID,
		"platform":   body.Platform,
		"message": map[string]interface{}{
			"type":      "text",
			"content":   body.Text,
			"image_url": body.ImageURL,
		},
		"agent_state": mergeImageSize(agentStateJSON, body.ImageSize),
	}

	resp, err := h.forwardToPythonV2(r, reqBody)
	if err != nil {
		// 6.6: Python Agent 层不可用 → SSE error event
		log.Printf("[ERROR] forward to Python: %v", err)
		state.Stage = model.StageIdle
		h.Session.Set(ctx, state)
		middleware.WriteJSON(w, model.CodePythonDown,
			model.NewErrorResponse(model.CodePythonDown, "agent service unavailable", traceID))
		return
	}

	// Update session state after run
	h.updateSessionFromResponse(ctx, state, resp)

	middleware.WriteJSON(w, 0, model.NewSuccessResponse(resp, traceID))
}

// handleResume sends a resume request to Python /agent/resume
func (h *Handler) handleResume(ctx context.Context, sessionID string, reply string, state *model.SessionState) (map[string]interface{}, error) {
	agentStateJSON := serializeAgentState(state.AgentState)

	reqBody := map[string]interface{}{
		"session_id":      sessionID,
		"user_id":         state.UserID,
		"tenant_id":       state.TenantID,
		"interrupt_reply": reply,
		"agent_state":     agentStateJSON,
	}

	return h.forwardResumeToPython(ctx, reqBody)
}

// updateSessionFromResponse updates Redis session state from Python response
func (h *Handler) updateSessionFromResponse(ctx context.Context, state *model.SessionState, resp map[string]interface{}) {
	data, ok := resp["data"].(map[string]interface{})
	if !ok {
		return
	}

	newAgentState, ok := data["new_agent_state"].(map[string]interface{})
	if !ok {
		newAgentState = map[string]interface{}{}
	}

	stageStr, _ := newAgentState["stage"].(string)
	switch stageStr {
	case "agent_interrupted":
		state.Stage = model.StageAgentInterrupted
	case "agent_running":
		state.Stage = model.StageAgentRunning
	default:
		state.Stage = model.StageIdle
	}

	state.AgentState = newAgentState

	if interrupt, ok := data["interrupt"].(map[string]interface{}); ok && interrupt != nil {
		interruptID, _ := interrupt["interrupt_id"].(string)
		label, _ := interrupt["label"].(string)
		question, _ := interrupt["question"].(string)
		timeoutS := 300
		if ts, ok := interrupt["timeout_s"].(float64); ok {
			timeoutS = int(ts)
		}

		options := []string{}
		if opts, ok := interrupt["options"].([]interface{}); ok {
			for _, o := range opts {
				if s, ok := o.(string); ok {
					options = append(options, s)
				}
			}
		}

		state.Interrupt = &model.InterruptRequest{
			InterruptID: interruptID,
			Label:       label,
			Question:    question,
			Options:     options,
			TimeoutS:    timeoutS,
			CreatedAt:   time.Now(),
		}
	} else {
		state.Interrupt = nil
	}

	if err := h.Session.Set(ctx, state); err != nil {
		log.Printf("[WARN] session set after response: %v", err)
	}
}

func serializeAgentState(state interface{}) map[string]interface{} {
	if state == nil {
		return map[string]interface{}{}
	}
	switch v := state.(type) {
	case map[string]interface{}:
		return v
	default:
		// Try JSON roundtrip
		b, err := json.Marshal(state)
		if err != nil {
			return map[string]interface{}{}
		}
		var result map[string]interface{}
		// S3-15: don't silently discard unmarshal error
		if err := json.Unmarshal(b, &result); err != nil {
			log.Printf("[WARN] serializeAgentState unmarshal failed: %v", err)
			return map[string]interface{}{}
		}
		return result
	}
}

// mergeImageSize adds image_size to the agent_state map for Step 6D >10MB check
func mergeImageSize(state map[string]interface{}, imageSize int64) map[string]interface{} {
	if imageSize <= 0 {
		return state
	}
	if state == nil {
		state = map[string]interface{}{}
	}
	state["image_size"] = imageSize
	return state
}

// ── SSE ──

// ChatStream serves GET /api/v1/chat/stream SSE.
func (h *Handler) ChatStream(w http.ResponseWriter, r *http.Request) {
	h.SSEBroker.Handler(w, r)
}
