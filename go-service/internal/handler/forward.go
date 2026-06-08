package handler

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/agentos/go-service/internal/config"
	"github.com/agentos/go-service/internal/middleware"
	"github.com/agentos/go-service/internal/platform"
	redisutil "github.com/agentos/go-service/internal/redis"
	"github.com/agentos/go-service/internal/session"
	"github.com/agentos/go-service/internal/sse"
)

type Handler struct {
	Config      *config.Config
	Session     *session.Manager
	SSEBroker   *sse.Broker
	Redis       *redisutil.Client
	PlatformMgr *platform.Manager
	WeCom       *platform.WeComAdapter
	Douyin      *platform.DouyinAdapter
	XHS         *platform.XHSAdapter
	httpClient  *http.Client
}

func New(cfg *config.Config, sm *session.Manager, broker *sse.Broker, redis *redisutil.Client) *Handler {
	return &Handler{
		Config:     cfg,
		Session:    sm,
		SSEBroker:  broker,
		Redis:      redis,
		httpClient: newHTTPClient(cfg.PythonServiceTimeout),
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
		httpClient:  newHTTPClient(cfg.PythonServiceTimeout),
	}

	// Wire platform adapters with the forward callback
	h.WeCom = platform.NewWeComAdapter(pm, h.forwardNormalized)
	h.Douyin = platform.NewDouyinAdapter(pm, h.forwardNormalized)
	h.XHS = platform.NewXHSAdapter(pm, h.forwardNormalized)

	return h
}

// pythonRequest is the shared low-level HTTP call for all Go→Python forwarding paths.
// Uses a shared http.Client with connection pooling; custom timeout uses context.WithTimeout.
func (h *Handler) pythonRequest(endpoint string, reqBody interface{}, timeout time.Duration) (map[string]interface{}, error) {
	payload, _ := json.Marshal(reqBody)

	targetURL := strings.TrimRight(h.Config.PythonServiceURL, "/") + endpoint

	var ctx context.Context
	var cancel context.CancelFunc
	if timeout > 0 {
		ctx, cancel = context.WithTimeout(context.Background(), timeout)
	} else {
		ctx, cancel = context.WithTimeout(context.Background(), h.Config.PythonServiceTimeout)
	}
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, targetURL, bytes.NewReader(payload))
	if err != nil {
		return nil, fmt.Errorf("python request failed: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := h.httpClient.Do(req)
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

// forwardToPython sends a simple request to Python /agent/run. Returns raw string for legacy callers.
func (h *Handler) forwardToPython(r *http.Request, sessionID, text, platformName string) (string, error) {
	body := map[string]interface{}{
		"session_id": sessionID,
		"text":       text,
		"platform":   platformName,
	}
	result, err := h.pythonRequest("/agent/run", body, 0)
	if err != nil {
		return "", err
	}
	b, _ := json.Marshal(result)
	return string(b), nil
}

// forwardNormalized sends a normalized InboundMessage to Python /agent/run.
// S3-02: Returns the full Python response (events array + data) instead of just reply text.
// The platform adapter uses this to extract card/interrupt/status events for active push.
func (h *Handler) forwardNormalized(ctx context.Context, msg *platform.InboundMessage) (string, error) {
	result, err := h.pythonRequest("/agent/run", map[string]interface{}{
		"session_id":  msg.SessionID,
		"user_id":     msg.UserID,
		"tenant_id":   msg.TenantID,
		"platform":    msg.Platform,
		"message":     msg.Message,
		"agent_state": msg.AgentState,
	}, 0)
	if err != nil {
		return "", err
	}

	// S3-02: Write card/interrupt/status events to SSE Broker so platform adapters
	// only need to handle active push; SSE subscribers get full event stream.
	if data, ok := result["data"].(map[string]interface{}); ok {
		if events, ok := data["events"].([]interface{}); ok {
			for _, e := range events {
				if evtMap, ok := e.(map[string]interface{}); ok {
					evtType, _ := evtMap["type"].(string)
					evtData := evtMap["data"]
					h.SSEBroker.Publish(msg.SessionID, sse.SSEEvent{Event: evtType, Data: evtData})
				}
			}
		}
	}

	// Return full JSON for adapter to parse
	b, _ := json.Marshal(result)
	return string(b), nil
}

// forwardToPythonV2 sends the full Step-6-compliant request to Python /agent/run.
func (h *Handler) forwardToPythonV2(r *http.Request, reqBody map[string]interface{}) (map[string]interface{}, error) {
	return h.pythonRequest("/agent/run", reqBody, 0)
}

// forwardResumeToPython sends a resume request to Python /agent/resume.
// S3-17: Accept context.Context instead of *http.Request for trace preservation.
func (h *Handler) forwardResumeToPython(ctx context.Context, reqBody map[string]interface{}) (map[string]interface{}, error) {
	return h.pythonRequest("/agent/resume", reqBody, 0)
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

// newHTTPClient creates a shared http.Client with connection pooling for reuse
// across all Go→Python forwarding requests.
func newHTTPClient(timeout time.Duration) *http.Client {
	return &http.Client{
		Timeout: timeout,
		Transport: &http.Transport{
			DialContext: (&net.Dialer{
				Timeout:   30 * time.Second,
				KeepAlive: 30 * time.Second,
			}).DialContext,
			MaxIdleConns:        100,
			MaxIdleConnsPerHost: 20,
			IdleConnTimeout:     90 * time.Second,
		},
	}
}
