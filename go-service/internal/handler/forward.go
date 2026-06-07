package handler

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"strconv"
	"strings"

	"github.com/agentos/go-service/internal/config"
	"github.com/agentos/go-service/internal/middleware"
	"github.com/agentos/go-service/internal/platform"
	redisutil "github.com/agentos/go-service/internal/redis"
	"github.com/agentos/go-service/internal/session"
	"github.com/agentos/go-service/internal/sse"
)

type Handler struct {
	Config     *config.Config
	Session    *session.Manager
	SSEBroker  *sse.Broker
	Redis      *redisutil.Client
	PlatformMgr *platform.Manager
	WeCom      *platform.WeComAdapter
	Douyin     *platform.DouyinAdapter
	XHS        *platform.XHSAdapter
}

func New(cfg *config.Config, sm *session.Manager, broker *sse.Broker, redis *redisutil.Client) *Handler {
	return &Handler{
		Config:    cfg,
		Session:   sm,
		SSEBroker: broker,
		Redis:     redis,
	}
}

// NewWithPlatforms creates a Handler with platform adapters initialized.
func NewWithPlatforms(cfg *config.Config, sm *session.Manager, broker *sse.Broker, redis *redisutil.Client, pm *platform.Manager) *Handler {
	h := &Handler{
		Config:      cfg,
		Session:     sm,
		SSEBroker:   broker,
		Redis:       redis,
		PlatformMgr: pm,
	}

	// Wire platform adapters with the forward callback
	h.WeCom = platform.NewWeComAdapter(pm, h.forwardNormalized)
	h.Douyin = platform.NewDouyinAdapter(pm, h.forwardNormalized)
	h.XHS = platform.NewXHSAdapter(pm, h.forwardNormalized)

	return h
}

// forwardToPython sends a simple request to Python /agent/run.
func (h *Handler) forwardToPython(r *http.Request, sessionID, text, platform string) (string, error) {
	body := map[string]interface{}{
		"session_id": sessionID,
		"text":       text,
		"platform":   platform,
	}
	payload, _ := json.Marshal(body)

	client := &http.Client{Timeout: h.Config.PythonServiceTimeout}
	resp, err := client.Post(
		strings.TrimRight(h.Config.PythonServiceURL, "/")+"/agent/run",
		"application/json",
		bytes.NewReader(payload),
	)
	if err != nil {
		return "", fmt.Errorf("python request failed: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", fmt.Errorf("read python response: %w", err)
	}
	if resp.StatusCode != 200 {
		return "", fmt.Errorf("python returned %d: %s", resp.StatusCode, string(respBody))
	}
	return string(respBody), nil
}

// forwardNormalized sends a normalized InboundMessage to Python /agent/run.
// This is the callback used by platform adapters.
func (h *Handler) forwardNormalized(ctx context.Context, msg *platform.InboundMessage) (string, error) {
	body := map[string]interface{}{
		"session_id":  msg.SessionID,
		"user_id":     msg.UserID,
		"tenant_id":   msg.TenantID,
		"platform":    msg.Platform,
		"message":     msg.Message,
		"agent_state": msg.AgentState,
	}
	payload, _ := json.Marshal(body)

	client := &http.Client{Timeout: h.Config.PythonServiceTimeout}
	resp, err := client.Post(
		strings.TrimRight(h.Config.PythonServiceURL, "/")+"/agent/run",
		"application/json",
		bytes.NewReader(payload),
	)
	if err != nil {
		return "", fmt.Errorf("python request failed: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", fmt.Errorf("read python response: %w", err)
	}
	if resp.StatusCode != 200 {
		return "", fmt.Errorf("python returned %d: %s", resp.StatusCode, string(respBody))
	}

	// Extract the reply text from Python's response
	var result map[string]interface{}
	if err := json.Unmarshal(respBody, &result); err != nil {
		return string(respBody), nil // Return raw if not JSON
	}

	// Try to get text content from the agent reply
	if data, ok := result["data"].(map[string]interface{}); ok {
		if reply, ok := data["reply"].(string); ok && reply != "" {
			return reply, nil
		}
		if messages, ok := data["messages"].([]interface{}); ok && len(messages) > 0 {
			if lastMsg, ok := messages[len(messages)-1].(map[string]interface{}); ok {
				if content, ok := lastMsg["content"].(string); ok {
					return content, nil
				}
			}
		}
	}

	return string(respBody), nil
}

// forwardToPythonV2 sends the full Step-6-compliant request to Python /agent/run
func (h *Handler) forwardToPythonV2(r *http.Request, reqBody map[string]interface{}) (map[string]interface{}, error) {
	payload, _ := json.Marshal(reqBody)

	client := &http.Client{Timeout: h.Config.PythonServiceTimeout}
	resp, err := client.Post(
		strings.TrimRight(h.Config.PythonServiceURL, "/")+"/agent/run",
		"application/json",
		bytes.NewReader(payload),
	)
	if err != nil {
		return nil, fmt.Errorf("python request failed: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read python response: %w", err)
	}
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("python returned %d: %s", resp.StatusCode, string(respBody))
	}

	var result map[string]interface{}
	if err := json.Unmarshal(respBody, &result); err != nil {
		return nil, fmt.Errorf("parse python response: %w", err)
	}
	return result, nil
}

// forwardResumeToPython sends a resume request to Python /agent/resume
func (h *Handler) forwardResumeToPython(r *http.Request, reqBody map[string]interface{}) (map[string]interface{}, error) {
	payload, _ := json.Marshal(reqBody)

	client := &http.Client{Timeout: h.Config.PythonServiceTimeout}
	resp, err := client.Post(
		strings.TrimRight(h.Config.PythonServiceURL, "/")+"/agent/resume",
		"application/json",
		bytes.NewReader(payload),
	)
	if err != nil {
		return nil, fmt.Errorf("python resume request failed: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read python resume response: %w", err)
	}
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("python resume returned %d: %s", resp.StatusCode, string(respBody))
	}

	var result map[string]interface{}
	if err := json.Unmarshal(respBody, &result); err != nil {
		return nil, fmt.Errorf("parse python resume response: %w", err)
	}
	return result, nil
}

// --- Webhook dispatch (Step 7 platform adapters) ---

// WebhookHandler returns a unified handler that dispatches to platform adapters.
// Handles both GET (URL verification) and POST (message receive).
func (h *Handler) WebhookHandler(w http.ResponseWriter, r *http.Request) {
	// Extract tenant_id from path: /api/v1/webhook/{platform}/{tenant_id}
	path := r.URL.Path
	parts := strings.Split(strings.TrimPrefix(path, "/"), "/")

	var platformName, tenantIDStr string
	// Path format: api/v1/webhook/{platform}/{tenant_id}
	if len(parts) >= 5 {
		platformName = parts[3] // wecom | douyin | xhs
		tenantIDStr = parts[4]
	}

	if platformName == "" || tenantIDStr == "" {
		w.WriteHeader(http.StatusBadRequest)
		w.Write([]byte(`{"code":4001,"message":"invalid webhook path"}`))
		return
	}

	tenantID, err := strconv.ParseInt(tenantIDStr, 10, 64)
	if err != nil {
		w.WriteHeader(http.StatusBadRequest)
		w.Write([]byte(`{"code":4001,"message":"invalid tenant_id"}`))
		return
	}

	// Ensure platform adapters are initialized
	if h.WeCom == nil || h.Douyin == nil || h.XHS == nil {
		w.WriteHeader(http.StatusInternalServerError)
		w.Write([]byte(`{"code":5001,"message":"platform adapters not initialized"}`))
		return
	}

	// Dispatch by HTTP method and platform
	switch r.Method {
	case http.MethodGet:
		h.handleWebhookGET(w, r, platformName, tenantID)
	case http.MethodPost:
		h.handleWebhookPOST(w, r, platformName, tenantID)
	default:
		w.WriteHeader(http.StatusMethodNotAllowed)
		w.Write([]byte(`{"code":4001,"message":"method not allowed"}`))
	}
}

func (h *Handler) handleWebhookGET(w http.ResponseWriter, r *http.Request, platformName string, tenantID int64) {
	traceID := middleware.GetTraceID(r.Context())

	switch platformName {
	case "wecom":
		h.WeCom.HandleVerify(w, r, tenantID)
	case "douyin":
		h.Douyin.HandleVerify(w, r, tenantID)
	case "xhs":
		h.XHS.HandleVerify(w, r, tenantID)
	default:
		w.WriteHeader(http.StatusBadRequest)
		w.Write([]byte(`{"code":4001,"message":"unknown platform"}`))
		log.Printf("[WEBHOOK] unknown platform '%s' for GET verification (trace=%s)", platformName, traceID)
	}
}

func (h *Handler) handleWebhookPOST(w http.ResponseWriter, r *http.Request, platformName string, tenantID int64) {
	traceID := middleware.GetTraceID(r.Context())

	switch platformName {
	case "wecom":
		h.WeCom.HandleMessage(w, r, tenantID)
	case "douyin":
		h.Douyin.HandleMessage(w, r, tenantID)
	case "xhs":
		h.XHS.HandleMessage(w, r, tenantID)
	default:
		w.WriteHeader(http.StatusBadRequest)
		w.Write([]byte(`{"code":4001,"message":"unknown platform"}`))
		log.Printf("[WEBHOOK] unknown platform '%s' for POST (trace=%s)", platformName, traceID)
	}
}
