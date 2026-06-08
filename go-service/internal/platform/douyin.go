package platform

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"time"

	"github.com/agentos/go-service/internal/middleware"
	"github.com/agentos/go-service/internal/model"
)

// DouyinAdapter implements the Douyin (抖音) platform adapter per doc section 7B.
type DouyinAdapter struct {
	mgr     *Manager
	forward func(ctx context.Context, msg *InboundMessage) (string, error)
}

// NewDouyinAdapter creates a Douyin adapter.
func NewDouyinAdapter(mgr *Manager, forwardFn func(ctx context.Context, msg *InboundMessage) (string, error)) *DouyinAdapter {
	return &DouyinAdapter{mgr: mgr, forward: forwardFn}
}

// HandleVerify processes GET URL verification (doc section 7B step 2).
func (a *DouyinAdapter) HandleVerify(w http.ResponseWriter, r *http.Request, tenantID int64) {
	traceID := middleware.GetTraceID(r.Context())

	params := DouyinVerifyParams{
		Signature: r.URL.Query().Get("signature"),
		Timestamp: r.URL.Query().Get("timestamp"),
		Nonce:     r.URL.Query().Get("nonce"),
		Echostr:   r.URL.Query().Get("echostr"),
	}

	if params.Signature == "" || params.Timestamp == "" || params.Nonce == "" || params.Echostr == "" {
		a.fail(w, r, fmt.Sprintf("%d", tenantID), "douyin", "missing required verification params")
		return
	}

	cfg, err := a.mgr.GetPlatformConfig(r.Context(), tenantID, "douyin")
	if err != nil {
		log.Printf("[DOUYIN] tenant %d platform config not found: %v", tenantID, err)
		a.fail(w, r, fmt.Sprintf("%d", tenantID), "douyin", "platform not configured")
		return
	}

	appSecret, err := a.mgr.DecryptAppSecret(cfg.AppSecretEncrypted)
	if err != nil {
		a.fail(w, r, fmt.Sprintf("%d", tenantID), "douyin", fmt.Sprintf("decrypt app_secret: %v", err))
		return
	}

	if !VerifyDouyinSignature(appSecret, params.Timestamp, params.Nonce, []byte(params.Echostr), params.Signature) {
		a.fail(w, r, fmt.Sprintf("%d", tenantID), "douyin", "HMAC-SHA256 signature verification failed")
		return
	}

	a.mgr.ResetFailCount(r.Context(), fmt.Sprintf("%d", tenantID), "douyin")

	log.Printf("[DOUYIN] tenant %d URL verification OK (trace=%s)", tenantID, traceID)
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	w.Write([]byte(params.Echostr))
}

// HandleMessage processes POST message (doc section 7B).
func (a *DouyinAdapter) HandleMessage(w http.ResponseWriter, r *http.Request, tenantID int64) {
	traceID := middleware.GetTraceID(r.Context())

	rawBody, err := io.ReadAll(r.Body)
	if err != nil {
		a.fail(w, r, fmt.Sprintf("%d", tenantID), "douyin", "read body failed")
		return
	}

	cfg, err := a.mgr.GetPlatformConfig(r.Context(), tenantID, "douyin")
	if err != nil {
		a.fail(w, r, fmt.Sprintf("%d", tenantID), "douyin", "platform not configured")
		return
	}

	appSecret, err := a.mgr.DecryptAppSecret(cfg.AppSecretEncrypted)
	if err != nil {
		a.fail(w, r, fmt.Sprintf("%d", tenantID), "douyin", fmt.Sprintf("decrypt app_secret: %v", err))
		return
	}

	signature := r.Header.Get("X-Douyin-Signature")
	timestamp := r.Header.Get("X-Douyin-Timestamp")
	nonce := r.Header.Get("X-Douyin-Nonce")

	if signature == "" {
		signature = r.URL.Query().Get("signature")
		timestamp = r.URL.Query().Get("timestamp")
		nonce = r.URL.Query().Get("nonce")
	}

	if !VerifyDouyinSignature(appSecret, timestamp, nonce, rawBody, signature) {
		a.fail(w, r, fmt.Sprintf("%d", tenantID), "douyin", "HMAC-SHA256 signature verification failed")
		return
	}

	var douyinBody DouyinWebhookBody
	if err := json.Unmarshal(rawBody, &douyinBody); err != nil {
		a.fail(w, r, fmt.Sprintf("%d", tenantID), "douyin", fmt.Sprintf("JSON parse: %v", err))
		return
	}

	a.mgr.ResetFailCount(r.Context(), fmt.Sprintf("%d", tenantID), "douyin")

	normalized := NormalizeDouyin(&douyinBody, tenantID)

	log.Printf("[DOUYIN] tenant %d user %s msg: type=%s content=%s (trace=%s)",
		tenantID, douyinBody.FromUserID, douyinBody.MsgType, douyinBody.Content.Text, traceID)

	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	w.Write([]byte(`{"code":0,"message":"received"}`))

	go a.asyncActivePush(cfg, &douyinBody, normalized, traceID)
}

func (a *DouyinAdapter) asyncActivePush(cfg *TenantPlatform, body *DouyinWebhookBody, normalized *InboundMessage, traceID string) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	result, err := a.forward(ctx, normalized)
	if err != nil {
		log.Printf("[DOUYIN] forward to Python failed (trace=%s): %v", traceID, err)
		a.pushTextMessage(cfg, body.FromUserID, body.ToUserID, "抱歉，处理超时，请稍后再试。")
		return
	}

	a.pushTextMessage(cfg, body.FromUserID, body.ToUserID, result)
}

// pushTextMessage sends a plain text message via Douyin active push API.
// POST /im/send_msg/ (doc section 7B)
// S7-05: Now uses access_token management instead of raw API call.
func (a *DouyinAdapter) pushTextMessage(cfg *TenantPlatform, fromUserID, toUserID, text string) {
	accessToken, err := a.getAccessToken(cfg)
	if err != nil {
		log.Printf("[DOUYIN] get access_token failed: %v", err)
		return
	}

	req := DouyinSendMsgReq{
		FromUserID: fromUserID,
		ToUserID:   toUserID,
		MsgType:    "text",
		Content:    text,
		TenantID:   cfg.AppID,
	}

	body, _ := json.Marshal(req)

	// S7-12: API URL from config or fallback to default
	apiURL := cfg.WebhookURL
	if apiURL == "" {
		apiURL = "https://open.douyin.com/im/send_msg/"
	}

	a.postWithRetry(apiURL, accessToken, body, 3)
}

// getAccessToken retrieves or refreshes Douyin access_token (S7-05).
func (a *DouyinAdapter) getAccessToken(cfg *TenantPlatform) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	cached, err := a.mgr.GetCachedAccessToken(ctx, "douyin", cfg.AppID)
	if err == nil && cached != "" {
		return cached, nil
	}

	appSecret, err := a.mgr.DecryptAppSecret(cfg.AppSecretEncrypted)
	if err != nil {
		return "", fmt.Errorf("decrypt app_secret: %w", err)
	}

	apiURL := fmt.Sprintf("https://open.douyin.com/oauth/access_token?client_key=%s&client_secret=%s&grant_type=client_credential",
		url.QueryEscape(cfg.AppID), url.QueryEscape(appSecret))

	resp, err := a.mgr.httpClient.Get(apiURL)
	if err != nil {
		return "", fmt.Errorf("douyin token request: %w", err)
	}
	defer func() {
		io.Copy(io.Discard, resp.Body)
		resp.Body.Close()
	}()

	var result struct {
		Data struct {
			AccessToken string `json:"access_token"`
			ExpiresIn   int    `json:"expires_in"`
		} `json:"data"`
		ErrorCode int    `json:"error_code"`
		ErrorMsg  string `json:"description"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return "", fmt.Errorf("parse douyin token response: %w", err)
	}
	if result.ErrorCode != 0 {
		return "", fmt.Errorf("douyin token error: code=%d msg=%s", result.ErrorCode, result.ErrorMsg)
	}

	if err := a.mgr.CacheAccessToken(ctx, "douyin", cfg.AppID, result.Data.AccessToken, result.Data.ExpiresIn); err != nil {
		log.Printf("[DOUYIN] cache access_token failed: %v", err)
	}

	return result.Data.AccessToken, nil
}

// postWithRetry sends a POST with bearer token and retry logic.
// S7-08: Properly drains and closes response body on every path.
func (a *DouyinAdapter) postWithRetry(apiURL, accessToken string, body []byte, maxRetry int) {
	for attempt := 0; attempt < maxRetry; attempt++ {
		req, err := http.NewRequest("POST", apiURL, bytes.NewReader(body))
		if err != nil {
			log.Printf("[DOUYIN] create request: %v", err)
			return
		}
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("Authorization", "Bearer "+accessToken)

		resp, err := a.mgr.httpClient.Do(req)
		if err != nil {
			log.Printf("[DOUYIN] push error (attempt %d/%d): %v", attempt+1, maxRetry, err)
			time.Sleep(time.Duration(attempt+1) * 500 * time.Millisecond)
			continue
		}

		// S7-08: drain and close resp.Body on EVERY path
		respBody, _ := io.ReadAll(resp.Body)
		resp.Body.Close()

		if resp.StatusCode == 200 {
			log.Printf("[DOUYIN] push OK to user (attempt %d)", attempt+1)
			return
		}

		log.Printf("[DOUYIN] push failed (attempt %d/%d): status=%d body=%s",
			attempt+1, maxRetry, resp.StatusCode, string(respBody))
		time.Sleep(time.Duration(attempt+1) * 500 * time.Millisecond)
	}
}

// PushInterruptCard pushes an interrupt card as numbered options (doc section 7B).
func (a *DouyinAdapter) PushInterruptCard(cfg *TenantPlatform, toUserID, fromUserID string, card *InterruptCard) {
	text := card.Question + "\n请回复："
	for i, opt := range card.Options {
		text += fmt.Sprintf("%d.%s ", i+1, opt)
	}
	a.pushTextMessage(cfg, fromUserID, toUserID, text)
}

func (a *DouyinAdapter) fail(w http.ResponseWriter, r *http.Request, tenantID, platform, reason string) {
	clientIP := r.RemoteAddr
	a.mgr.LogSecurityFailure(r.Context(), tenantID, platform, clientIP, reason)
	w.WriteHeader(http.StatusForbidden)
	middleware.WriteJSON(w, model.CodeForbidden,
		model.NewErrorResponse(model.CodeForbidden, "signature verification failed", middleware.GetTraceID(r.Context())))
}
