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
// Douyin sends GET with signature, timestamp, nonce, echostr.
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

	// HMAC-SHA256 verification (doc section 7.2)
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

	// Verify HMAC-SHA256 signature on the raw body (doc section 7.2)
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

	// Parse webhook body
	var douyinBody DouyinWebhookBody
	if err := json.Unmarshal(rawBody, &douyinBody); err != nil {
		a.fail(w, r, fmt.Sprintf("%d", tenantID), "douyin", fmt.Sprintf("JSON parse: %v", err))
		return
	}

	a.mgr.ResetFailCount(r.Context(), fmt.Sprintf("%d", tenantID), "douyin")

	normalized := NormalizeDouyin(&douyinBody, tenantID)

	log.Printf("[DOUYIN] tenant %d user %s msg: type=%s content=%s (trace=%s)",
		tenantID, douyinBody.FromUserID, douyinBody.MsgType, douyinBody.Content.Text, traceID)

	// Passive reply 200 OK (doc section 7B)
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	w.Write([]byte(`{"code":0,"message":"received"}`))

	// Async goroutine for active push (doc section 7B)
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

	// Douyin doesn't support cards; push as text (doc section 7B)
	a.pushTextMessage(cfg, body.FromUserID, body.ToUserID, result)
}

// pushTextMessage sends a plain text message via Douyin active push API.
// POST /im/send_msg/ (doc section 7B)
func (a *DouyinAdapter) pushTextMessage(cfg *TenantPlatform, fromUserID, toUserID, text string) {
	appSecret, err := a.mgr.DecryptAppSecret(cfg.AppSecretEncrypted)
	if err != nil {
		log.Printf("[DOUYIN] decrypt app_secret: %v", err)
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
	apiURL := "https://open.douyin.com/im/send_msg/"

	resp, err := a.mgr.httpClient.Post(apiURL, "application/json", bytes.NewReader(body))
	if err != nil {
		log.Printf("[DOUYIN] active push error: %v", err)
		// Retry up to 3 times (doc section 7A AccessToken retry pattern)
		for i := 0; i < 3; i++ {
			time.Sleep(time.Duration(i+1) * 500 * time.Millisecond)
			resp, err = a.mgr.httpClient.Post(apiURL, "application/json", bytes.NewReader(body))
			if err == nil {
				break
			}
			log.Printf("[DOUYIN] retrying push (%d/3)", i+1)
		}
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		respBody, _ := io.ReadAll(resp.Body)
		log.Printf("[DOUYIN] push failed: status=%d body=%s", resp.StatusCode, string(respBody))
		return
	}

	log.Printf("[DOUYIN] active push OK to user %s", toUserID)
	_ = appSecret
}

// PushInterruptCard pushes an interrupt card as numbered options (doc section 7B: 中断反调).
// Douyin doesn't support rich cards, so we use text + numeric options:
// "请回复：1.没有过敏 2.烟酰胺过敏 3.水杨酸过敏"
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
