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

// XHSAdapter implements the Xiaohongshu (小红书) platform adapter per doc section 7C.
type XHSAdapter struct {
	mgr     *Manager
	forward func(ctx context.Context, msg *InboundMessage) (string, error)
}

// NewXHSAdapter creates a Xiaohongshu adapter.
func NewXHSAdapter(mgr *Manager, forwardFn func(ctx context.Context, msg *InboundMessage) (string, error)) *XHSAdapter {
	return &XHSAdapter{mgr: mgr, forward: forwardFn}
}

// HandleVerify processes GET URL verification (doc section 7C step 2).
func (a *XHSAdapter) HandleVerify(w http.ResponseWriter, r *http.Request, tenantID int64) {
	traceID := middleware.GetTraceID(r.Context())

	params := XHSVerifyParams{
		Signature: r.URL.Query().Get("signature"),
		Timestamp: r.URL.Query().Get("timestamp"),
		Nonce:     r.URL.Query().Get("nonce"),
		Echostr:   r.URL.Query().Get("echostr"),
	}

	if params.Signature == "" || params.Timestamp == "" || params.Nonce == "" || params.Echostr == "" {
		a.fail(w, r, fmt.Sprintf("%d", tenantID), "xhs", "missing required verification params")
		return
	}

	cfg, err := a.mgr.GetPlatformConfig(r.Context(), tenantID, "xhs")
	if err != nil {
		log.Printf("[XHS] tenant %d platform config not found: %v", tenantID, err)
		a.fail(w, r, fmt.Sprintf("%d", tenantID), "xhs", "platform not configured")
		return
	}

	// S7-04: Real RSA verification using the public key from config
	// The app_id field stores the XHS public key (PEM format)
	payload := params.Timestamp + "\n" + params.Nonce + "\n" + params.Echostr
	if !VerifyXHSRSA([]byte(payload), params.Signature, cfg.AppID) {
		a.fail(w, r, fmt.Sprintf("%d", tenantID), "xhs", "RSA signature verification failed")
		return
	}

	a.mgr.ResetFailCount(r.Context(), fmt.Sprintf("%d", tenantID), "xhs")

	log.Printf("[XHS] tenant %d URL verification OK (trace=%s)", tenantID, traceID)
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	w.Write([]byte(params.Echostr))
}

// HandleMessage processes POST message (doc section 7C).
func (a *XHSAdapter) HandleMessage(w http.ResponseWriter, r *http.Request, tenantID int64) {
	traceID := middleware.GetTraceID(r.Context())

	rawBody, err := io.ReadAll(r.Body)
	if err != nil {
		a.fail(w, r, fmt.Sprintf("%d", tenantID), "xhs", "read body failed")
		return
	}

	cfg, err := a.mgr.GetPlatformConfig(r.Context(), tenantID, "xhs")
	if err != nil {
		a.fail(w, r, fmt.Sprintf("%d", tenantID), "xhs", "platform not configured")
		return
	}

	// RSA signature verification on the raw body
	signature := r.Header.Get("X-XHS-Signature")
	if signature == "" {
		signature = r.URL.Query().Get("signature")
	}

	if !VerifyXHSRSA(rawBody, signature, cfg.AppID) {
		a.fail(w, r, fmt.Sprintf("%d", tenantID), "xhs", "RSA signature verification failed")
		return
	}

	var xhsBody XHSWebhookBody
	if err := json.Unmarshal(rawBody, &xhsBody); err != nil {
		a.fail(w, r, fmt.Sprintf("%d", tenantID), "xhs", fmt.Sprintf("JSON parse: %v", err))
		return
	}

	a.mgr.ResetFailCount(r.Context(), fmt.Sprintf("%d", tenantID), "xhs")

	normalized := NormalizeXHS(&xhsBody, tenantID)

	log.Printf("[XHS] tenant %d user %s msg: type=%s content=%s (trace=%s)",
		tenantID, xhsBody.FromUserID, xhsBody.MsgType, xhsBody.Content, traceID)

	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	w.Write([]byte(`{"code":0,"message":"received"}`))

	go a.asyncActivePush(cfg, &xhsBody, normalized, traceID)
}

func (a *XHSAdapter) asyncActivePush(cfg *TenantPlatform, body *XHSWebhookBody, normalized *InboundMessage, traceID string) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	result, err := a.forward(ctx, normalized)
	if err != nil {
		log.Printf("[XHS] forward to Python failed (trace=%s): %v", traceID, err)
		a.pushMessage(cfg, body.ToUserID, body.FromUserID, "抱歉，处理超时，请稍后再试。")
		return
	}

	a.pushMessage(cfg, body.ToUserID, body.FromUserID, result)
}

// pushMessage sends a message via Xiaohongshu private message API (doc section 7C).
// S7-06: Now uses access_token management with Bearer auth header.
func (a *XHSAdapter) pushMessage(cfg *TenantPlatform, fromUserID, toUserID, text string) {
	accessToken, err := a.getAccessToken(cfg)
	if err != nil {
		log.Printf("[XHS] get access_token failed: %v", err)
		return
	}

	req := XHSSendMsgReq{
		ToUserID: toUserID,
		MsgType:  "text",
		Content:  text,
	}

	body, _ := json.Marshal(req)

	// S7-13: API URL from config or fallback
	apiURL := cfg.WebhookURL
	if apiURL == "" {
		apiURL = "https://open.xiaohongshu.com/api/im/send_msg"
	}

	a.postWithRetry(apiURL, accessToken, body, 3)
}

// getAccessToken retrieves or refreshes XHS access_token (S7-06).
func (a *XHSAdapter) getAccessToken(cfg *TenantPlatform) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	cached, err := a.mgr.GetCachedAccessToken(ctx, "xhs", cfg.AppID)
	if err == nil && cached != "" {
		return cached, nil
	}

	appSecret, err := a.mgr.DecryptAppSecret(cfg.AppSecretEncrypted)
	if err != nil {
		return "", fmt.Errorf("decrypt app_secret: %w", err)
	}

	apiURL := fmt.Sprintf("https://open.xiaohongshu.com/oauth/access_token?app_id=%s&app_secret=%s&grant_type=client_credential",
		url.QueryEscape(cfg.AppID), url.QueryEscape(appSecret))

	resp, err := a.mgr.httpClient.Get(apiURL)
	if err != nil {
		return "", fmt.Errorf("xhs token request: %w", err)
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
		ErrorMsg  string `json:"error_msg"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return "", fmt.Errorf("parse xhs token response: %w", err)
	}
	if result.ErrorCode != 0 {
		return "", fmt.Errorf("xhs token error: code=%d msg=%s", result.ErrorCode, result.ErrorMsg)
	}

	if err := a.mgr.CacheAccessToken(ctx, "xhs", cfg.AppID, result.Data.AccessToken, result.Data.ExpiresIn); err != nil {
		log.Printf("[XHS] cache access_token failed: %v", err)
	}

	return result.Data.AccessToken, nil
}

// postWithRetry sends a POST with bearer token and retry logic.
// S7-09: Properly drains and closes response body on every path.
func (a *XHSAdapter) postWithRetry(apiURL, accessToken string, body []byte, maxRetry int) {
	for attempt := 0; attempt < maxRetry; attempt++ {
		req, err := http.NewRequest("POST", apiURL, bytes.NewReader(body))
		if err != nil {
			log.Printf("[XHS] create request: %v", err)
			return
		}
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("Authorization", "Bearer "+accessToken)

		resp, err := a.mgr.httpClient.Do(req)
		if err != nil {
			log.Printf("[XHS] push error (attempt %d/%d): %v", attempt+1, maxRetry, err)
			time.Sleep(time.Duration(attempt+1) * 500 * time.Millisecond)
			continue
		}

		// S7-09: drain and close on EVERY path
		respBody, _ := io.ReadAll(resp.Body)
		resp.Body.Close()

		if resp.StatusCode == 200 {
			log.Printf("[XHS] push OK to user (attempt %d)", attempt+1)
			return
		}

		log.Printf("[XHS] push failed (attempt %d/%d): status=%d body=%s",
			attempt+1, maxRetry, resp.StatusCode, string(respBody))
		time.Sleep(time.Duration(attempt+1) * 500 * time.Millisecond)
	}
}

func (a *XHSAdapter) fail(w http.ResponseWriter, r *http.Request, tenantID, platform, reason string) {
	clientIP := r.RemoteAddr
	a.mgr.LogSecurityFailure(r.Context(), tenantID, platform, clientIP, reason)
	w.WriteHeader(http.StatusForbidden)
	middleware.WriteJSON(w, model.CodeForbidden,
		model.NewErrorResponse(model.CodeForbidden, "signature verification failed", middleware.GetTraceID(r.Context())))
}
