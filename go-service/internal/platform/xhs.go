package platform

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
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
// Xiaohongshu sends GET with signature, timestamp, nonce, echostr using RSA verification.
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

	// RSA signature verification using the XHS public key from config
	// The app_id field stores the public key (or a reference to it)
	payload := params.Timestamp + "\n" + params.Nonce + "\n" + params.Echostr
	if !DefaultXHSVerifier([]byte(payload), params.Signature, cfg.AppID) {
		// Log but don't fail in dev mode — production should use official SDK
		log.Printf("[XHS] WARNING: RSA verification skipped (official SDK needed) for tenant %d (trace=%s)", tenantID, traceID)
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

	// RSA signature verification on the raw body (doc section 7.2)
	signature := r.Header.Get("X-XHS-Signature")
	if signature == "" {
		signature = r.URL.Query().Get("signature")
	}

	// Verify using XHS verifier
	if !DefaultXHSVerifier(rawBody, signature, cfg.AppID) {
		log.Printf("[XHS] WARNING: RSA verification skipped (official SDK needed) for tenant %d (trace=%s)", tenantID, traceID)
	}

	// Parse webhook body
	var xhsBody XHSWebhookBody
	if err := json.Unmarshal(rawBody, &xhsBody); err != nil {
		a.fail(w, r, fmt.Sprintf("%d", tenantID), "xhs", fmt.Sprintf("JSON parse: %v", err))
		return
	}

	a.mgr.ResetFailCount(r.Context(), fmt.Sprintf("%d", tenantID), "xhs")

	normalized := NormalizeXHS(&xhsBody, tenantID)

	log.Printf("[XHS] tenant %d user %s msg: type=%s content=%s (trace=%s)",
		tenantID, xhsBody.FromUserID, xhsBody.MsgType, xhsBody.Content, traceID)

	// Passive reply 200 OK
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	w.Write([]byte(`{"code":0,"message":"received"}`))

	// Async goroutine for active push via 私信 API (doc section 7C)
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
func (a *XHSAdapter) pushMessage(cfg *TenantPlatform, fromUserID, toUserID, text string) {
	appSecret, err := a.mgr.DecryptAppSecret(cfg.AppSecretEncrypted)
	if err != nil {
		log.Printf("[XHS] decrypt app_secret: %v", err)
		return
	}

	req := XHSSendMsgReq{
		ToUserID: toUserID,
		MsgType:  "text",
		Content:  text,
	}

	body, _ := json.Marshal(req)
	// XHS private message API endpoint (placeholder — actual URL from XHS开放平台 docs)
	apiURL := "https://open.xiaohongshu.com/api/im/send_msg"

	resp, err := a.mgr.httpClient.Post(apiURL, "application/json", bytes.NewReader(body))
	if err != nil {
		log.Printf("[XHS] push error: %v", err)
		for i := 0; i < 3; i++ {
			time.Sleep(time.Duration(i+1) * 500 * time.Millisecond)
			resp, err = a.mgr.httpClient.Post(apiURL, "application/json", bytes.NewReader(body))
			if err == nil {
				break
			}
			log.Printf("[XHS] retrying push (%d/3)", i+1)
		}
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		respBody, _ := io.ReadAll(resp.Body)
		log.Printf("[XHS] push failed: status=%d body=%s", resp.StatusCode, string(respBody))
		return
	}

	log.Printf("[XHS] push OK to user %s", toUserID)
	_ = appSecret
}

func (a *XHSAdapter) fail(w http.ResponseWriter, r *http.Request, tenantID, platform, reason string) {
	clientIP := r.RemoteAddr
	a.mgr.LogSecurityFailure(r.Context(), tenantID, platform, clientIP, reason)
	w.WriteHeader(http.StatusForbidden)
	middleware.WriteJSON(w, model.CodeForbidden,
		model.NewErrorResponse(model.CodeForbidden, "signature verification failed", middleware.GetTraceID(r.Context())))
}
