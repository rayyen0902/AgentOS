package platform

import (
	"bytes"
	"context"
	"crypto/aes"
	"crypto/cipher"
	"encoding/base64"
	"encoding/json"
	"encoding/xml"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"time"

	"github.com/agentos/go-service/internal/middleware"
	"github.com/agentos/go-service/internal/model"
)

// WeComAdapter implements the WeCom (企业微信) platform adapter per doc section 7A.
type WeComAdapter struct {
	mgr     *Manager
	forward func(ctx context.Context, msg *InboundMessage) (string, error)
}

// NewWeComAdapter creates a WeCom adapter.
func NewWeComAdapter(mgr *Manager, forwardFn func(ctx context.Context, msg *InboundMessage) (string, error)) *WeComAdapter {
	return &WeComAdapter{mgr: mgr, forward: forwardFn}
}

// HandleVerify processes GET URL verification (doc section 7A step 2).
func (a *WeComAdapter) HandleVerify(w http.ResponseWriter, r *http.Request, tenantID int64) {
	traceID := middleware.GetTraceID(r.Context())

	params := WeComVerifyParams{
		MsgSignature: r.URL.Query().Get("msg_signature"),
		Timestamp:    r.URL.Query().Get("timestamp"),
		Nonce:        r.URL.Query().Get("nonce"),
		Echostr:      r.URL.Query().Get("echostr"),
	}

	if params.MsgSignature == "" || params.Timestamp == "" || params.Nonce == "" || params.Echostr == "" {
		a.fail(w, r, fmt.Sprintf("%d", tenantID), "wecom", "missing required verification params")
		return
	}

	cfg, err := a.mgr.GetPlatformConfig(r.Context(), tenantID, "wecom")
	if err != nil {
		log.Printf("[WECOM] tenant %d platform config not found: %v", tenantID, err)
		a.fail(w, r, fmt.Sprintf("%d", tenantID), "wecom", "platform not configured")
		return
	}

	if !VerifyWeComSignature(cfg.Token, params.Timestamp, params.Nonce, params.Echostr, params.MsgSignature) {
		a.fail(w, r, fmt.Sprintf("%d", tenantID), "wecom", "signature verification failed")
		return
	}

	// S7-01: base64-decode echostr before AES decrypt
	decoded, err := base64.StdEncoding.DecodeString(params.Echostr)
	if err != nil {
		a.fail(w, r, fmt.Sprintf("%d", tenantID), "wecom", fmt.Sprintf("echostr base64 decode: %v", err))
		return
	}

	aesKey, err := a.decodeAESKey(cfg.EncodingAESKey)
	if err != nil {
		a.fail(w, r, fmt.Sprintf("%d", tenantID), "wecom", fmt.Sprintf("decode AES key: %v", err))
		return
	}

	decrypted, err := a.aesDecrypt(decoded, aesKey)
	if err != nil {
		a.fail(w, r, fmt.Sprintf("%d", tenantID), "wecom", fmt.Sprintf("echostr AES decrypt: %v", err))
		return
	}

	a.mgr.ResetFailCount(r.Context(), fmt.Sprintf("%d", tenantID), "wecom")

	log.Printf("[WECOM] tenant %d URL verification OK (trace=%s)", tenantID, traceID)
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	w.Write([]byte(decrypted))
}

// HandleMessage processes POST message (doc section 7A).
func (a *WeComAdapter) HandleMessage(w http.ResponseWriter, r *http.Request, tenantID int64) {
	traceID := middleware.GetTraceID(r.Context())

	rawBody, err := io.ReadAll(r.Body)
	if err != nil {
		a.fail(w, r, fmt.Sprintf("%d", tenantID), "wecom", "read body failed")
		return
	}

	var encMsg WeComEncryptedMsg
	if err := xml.Unmarshal(rawBody, &encMsg); err != nil {
		a.fail(w, r, fmt.Sprintf("%d", tenantID), "wecom", fmt.Sprintf("XML parse: %v", err))
		return
	}

	cfg, err := a.mgr.GetPlatformConfig(r.Context(), tenantID, "wecom")
	if err != nil {
		a.fail(w, r, fmt.Sprintf("%d", tenantID), "wecom", "platform not configured")
		return
	}

	msgSignature := r.URL.Query().Get("msg_signature")
	timestamp := r.URL.Query().Get("timestamp")
	nonce := r.URL.Query().Get("nonce")

	if !VerifyWeComSignature(cfg.Token, timestamp, nonce, encMsg.Encrypt, msgSignature) {
		a.fail(w, r, fmt.Sprintf("%d", tenantID), "wecom", "signature verification failed")
		return
	}

	// S7-02: base64-decode the encrypted body then AES decrypt with properly decoded key
	encryptedBytes, err := base64.StdEncoding.DecodeString(encMsg.Encrypt)
	if err != nil {
		a.fail(w, r, fmt.Sprintf("%d", tenantID), "wecom", fmt.Sprintf("decode encrypted body: %v", err))
		return
	}

	aesKey, err := a.decodeAESKey(cfg.EncodingAESKey)
	if err != nil {
		a.fail(w, r, fmt.Sprintf("%d", tenantID), "wecom", fmt.Sprintf("decode AES key: %v", err))
		return
	}

	decryptedXML, err := a.aesDecrypt(encryptedBytes, aesKey)
	if err != nil {
		a.fail(w, r, fmt.Sprintf("%d", tenantID), "wecom", fmt.Sprintf("AES decrypt body: %v", err))
		return
	}

	var decMsg WeComDecryptedMsg
	if err := xml.Unmarshal([]byte(decryptedXML), &decMsg); err != nil {
		a.fail(w, r, fmt.Sprintf("%d", tenantID), "wecom", fmt.Sprintf("parse decrypted XML: %v", err))
		return
	}

	a.mgr.ResetFailCount(r.Context(), fmt.Sprintf("%d", tenantID), "wecom")

	normalized := NormalizeWeCom(&decMsg, tenantID, decMsg.FromUserName)

	log.Printf("[WECOM] tenant %d user %s msg: type=%s content=%s (trace=%s)",
		tenantID, decMsg.FromUserName, decMsg.MsgType, decMsg.Content, traceID)

	// Passive reply (doc section 7A: sync 200 OK with XML)
	reply := WeComPassiveReply{
		ToUserName:   decMsg.FromUserName,
		FromUserName: decMsg.ToUserName,
		CreateTime:   time.Now().Unix(),
		MsgType:      "text",
		Content:      "收到，正在处理...",
	}
	replyXML, _ := xml.Marshal(reply)

	w.Header().Set("Content-Type", "application/xml; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	w.Write(replyXML)

	// Async goroutine for active push (doc section 7A: T+800ms → T+3.1s)
	go a.asyncActivePush(cfg, &decMsg, normalized, traceID)
}

// asyncActivePush runs in a goroutine to forward to Python and push results via WeCom API.
func (a *WeComAdapter) asyncActivePush(cfg *TenantPlatform, decMsg *WeComDecryptedMsg, normalized *InboundMessage, traceID string) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	result, err := a.forward(ctx, normalized)
	if err != nil {
		log.Printf("[WECOM] forward to Python failed (trace=%s): %v", traceID, err)
		a.pushTextMessage(cfg, decMsg.FromUserName, "抱歉，处理超时，请稍后再试。")
		return
	}

	a.pushResultCard(cfg, decMsg.FromUserName, result)
}

func (a *WeComAdapter) pushTextMessage(cfg *TenantPlatform, openID, text string) {
	accessToken, err := a.getAccessToken(cfg)
	if err != nil {
		log.Printf("[WECOM] get access_token failed: %v", err)
		return
	}

	agentID := a.getAgentID(cfg)
	push := WeComActivePush{
		ToUser:  openID,
		MsgType: "text",
		AgentID: agentID,
		Text:    &WeComTextContent{Content: text},
	}

	a.sendActivePush(accessToken, push, 0, cfg)
}

func (a *WeComAdapter) pushResultCard(cfg *TenantPlatform, openID, result string) {
	accessToken, err := a.getAccessToken(cfg)
	if err != nil {
		log.Printf("[WECOM] get access_token failed: %v", err)
		return
	}

	title := result
	if len(title) > 40 {
		title = title[:40]
	}
	description := result
	if len(description) > 120 {
		description = description[:120]
	}

	agentID := a.getAgentID(cfg)
	push := WeComActivePush{
		ToUser:  openID,
		MsgType: "news",
		AgentID: agentID,
		News: &WeComNewsContent{
			Articles: []WeComArticle{{Title: title, Description: description, URL: ""}},
		},
	}

	a.sendActivePush(accessToken, push, 0, cfg)
}

// getAgentID reads the AgentID from config (S7-07 fix: was hardcoded 1000002).
// Falls back to 1000002 if not configured in DB (default WeCom agent).
func (a *WeComAdapter) getAgentID(cfg *TenantPlatform) int {
	if cfg.WeComAgentID != 0 {
		return cfg.WeComAgentID
	}
	return 1000002
}

// sendActivePush calls POST /cgi-bin/message/send with retry (max 3 per doc section 7A).
func (a *WeComAdapter) sendActivePush(accessToken string, push WeComActivePush, retryCount int, cfg *TenantPlatform) {
	body, err := json.Marshal(push)
	if err != nil {
		log.Printf("[WECOM] marshal push body: %v", err)
		return
	}

	apiURL := fmt.Sprintf("https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token=%s", accessToken)

	resp, err := a.mgr.httpClient.Post(apiURL, "application/json", bytes.NewReader(body))
	if err != nil {
		log.Printf("[WECOM] active push error: %v", err)
		if retryCount < 3 {
			log.Printf("[WECOM] retrying active push (%d/3)", retryCount+1)
			time.Sleep(time.Duration(retryCount+1) * 500 * time.Millisecond)
			a.sendActivePush(accessToken, push, retryCount+1, cfg)
		}
		return
	}
	// S7-08: resp.Body is closed via defer, but we must drain it before defer
	defer func() {
		io.Copy(io.Discard, resp.Body)
		resp.Body.Close()
	}()

	var tokenResp WeComTokenResponse
	if err := json.NewDecoder(resp.Body).Decode(&tokenResp); err != nil {
		log.Printf("[WECOM] parse push response: %v", err)
		return
	}

	if tokenResp.ErrCode != 0 {
		log.Printf("[WECOM] push failed: errcode=%d errmsg=%s", tokenResp.ErrCode, tokenResp.ErrMsg)
		if tokenResp.ErrCode == 42001 || tokenResp.ErrCode == 40014 {
			if retryCount < 3 {
				// S7-14: use context.WithTimeout instead of context.Background()
				delCtx, delCancel := context.WithTimeout(context.Background(), 3*time.Second)
				a.mgr.redis.Delete(delCtx, fmt.Sprintf(accessTokenKeyPrefix, "wecom", cfg.AppID))
				delCancel()
				time.Sleep(time.Duration(retryCount+1) * 500 * time.Millisecond)
				newToken, err := a.getAccessToken(cfg)
				if err == nil {
					a.sendActivePush(newToken, push, retryCount+1, cfg)
				}
			}
		}
		return
	}

	log.Printf("[WECOM] active push OK to user %s", push.ToUser)
}

// getAccessToken retrieves or refreshes WeCom access_token (doc section 7A: Redis TTL = expires_in - 60s).
func (a *WeComAdapter) getAccessToken(cfg *TenantPlatform) (string, error) {
	// S7-14: use context.WithTimeout
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	cached, err := a.mgr.GetCachedAccessToken(ctx, "wecom", cfg.AppID)
	if err == nil && cached != "" {
		return cached, nil
	}

	appSecret, err := a.mgr.DecryptAppSecret(cfg.AppSecretEncrypted)
	if err != nil {
		return "", fmt.Errorf("decrypt app_secret: %w", err)
	}

	apiURL := fmt.Sprintf("https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid=%s&corpsecret=%s",
		url.QueryEscape(cfg.AppID), url.QueryEscape(appSecret))

	resp, err := a.mgr.httpClient.Get(apiURL)
	if err != nil {
		return "", fmt.Errorf("gettoken request: %w", err)
	}
	defer func() {
		io.Copy(io.Discard, resp.Body)
		resp.Body.Close()
	}()

	var tokenResp WeComTokenResponse
	if err := json.NewDecoder(resp.Body).Decode(&tokenResp); err != nil {
		return "", fmt.Errorf("parse gettoken response: %w", err)
	}

	if tokenResp.ErrCode != 0 {
		return "", fmt.Errorf("gettoken error: errcode=%d errmsg=%s", tokenResp.ErrCode, tokenResp.ErrMsg)
	}

	if err := a.mgr.CacheAccessToken(ctx, "wecom", cfg.AppID, tokenResp.AccessToken, tokenResp.ExpiresIn); err != nil {
		log.Printf("[WECOM] cache access_token failed: %v", err)
	}

	return tokenResp.AccessToken, nil
}

// --- AES crypto helpers for WeCom (AES-256-CBC, IV = key[:16]) ---

// decodeAESKey converts the 43-char base64 EncodingAESKey to the 32-byte AES key.
// WeCom provides a 43-char base64 string; we decode to get 32 bytes.
func (a *WeComAdapter) decodeAESKey(encodingAESKey string) ([]byte, error) {
	key, err := base64.StdEncoding.DecodeString(encodingAESKey + "=")
	if err != nil {
		return nil, fmt.Errorf("decode AES key: %w", err)
	}
	if len(key) != 32 {
		return nil, fmt.Errorf("AES key must be 32 bytes, got %d", len(key))
	}
	return key, nil
}

func (a *WeComAdapter) aesDecrypt(ciphertext []byte, key []byte) (string, error) {
	block, err := aes.NewCipher(key)
	if err != nil {
		return "", fmt.Errorf("aes new cipher: %w", err)
	}

	if len(ciphertext) < aes.BlockSize {
		return "", fmt.Errorf("ciphertext too short")
	}

	iv := key[:aes.BlockSize]
	mode := cipher.NewCBCDecrypter(block, iv)

	plaintext := make([]byte, len(ciphertext))
	mode.CryptBlocks(plaintext, ciphertext)

	plaintext, err = pkcs7Unpad(plaintext)
	if err != nil {
		return "", fmt.Errorf("pkcs7 unpad: %w", err)
	}

	return string(plaintext), nil
}

// aesEncrypt encrypts data using AES-CBC with the given key.
// S7-03: now properly accepts the decoded key from decodeAESKey.
func (a *WeComAdapter) aesEncrypt(plaintext []byte, key []byte) (string, error) {
	block, err := aes.NewCipher(key)
	if err != nil {
		return "", fmt.Errorf("aes new cipher: %w", err)
	}

	padding := aes.BlockSize - (len(plaintext) % aes.BlockSize)
	padText := make([]byte, len(plaintext)+padding)
	copy(padText, plaintext)
	for i := len(plaintext); i < len(padText); i++ {
		padText[i] = byte(padding)
	}

	iv := key[:aes.BlockSize]
	mode := cipher.NewCBCEncrypter(block, iv)

	ciphertext := make([]byte, len(padText))
	mode.CryptBlocks(ciphertext, padText)

	return base64.StdEncoding.EncodeToString(ciphertext), nil
}

func (a *WeComAdapter) fail(w http.ResponseWriter, r *http.Request, tenantID, platform, reason string) {
	clientIP := r.RemoteAddr
	a.mgr.LogSecurityFailure(r.Context(), tenantID, platform, clientIP, reason)
	// Per doc section 7.2: verification failure → 403
	w.WriteHeader(http.StatusForbidden)
	middleware.WriteJSON(w, model.CodeForbidden,
		model.NewErrorResponse(model.CodeForbidden, "signature verification failed", middleware.GetTraceID(r.Context())))
}
