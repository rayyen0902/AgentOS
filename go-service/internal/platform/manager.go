package platform

import (
	"bytes"
	"context"
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/sha256"
	"database/sql"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"time"

	redisutil "github.com/agentos/go-service/internal/redis"
)

// Manager handles platform configuration CRUD and token caching.
// Uses tenant_platforms table in PostgreSQL and Redis for AccessToken caching.
type Manager struct {
	db              *sql.DB
	redis           *redisutil.Client
	encryptionKey   []byte // AES-256 key for app_secret encryption
	alertWebhookURL string
	httpClient      *http.Client
}

// NewManager creates a new platform Manager.
func NewManager(db *sql.DB, redis *redisutil.Client, encryptionKey, alertWebhookURL string) *Manager {
	return &Manager{
		db:              db,
		redis:           redis,
		encryptionKey:   []byte(encryptionKey),
		alertWebhookURL: alertWebhookURL,
		httpClient:      &http.Client{Timeout: 10 * time.Second},
	}
}

// --- tenant_platforms CRUD (doc section 7.5) ---

// GetPlatformConfig retrieves platform configuration by tenant_id and platform type.
func (m *Manager) GetPlatformConfig(ctx context.Context, tenantID int64, platform string) (*TenantPlatform, error) {
	var tp TenantPlatform
	var createdAt time.Time
	err := m.db.QueryRowContext(ctx, `
		SELECT id, tenant_id, platform, app_id, app_secret_hash, app_secret_encrypted,
		       COALESCE(token, ''), COALESCE(encoding_aes_key, ''), COALESCE(webhook_url, ''), status, created_at
		FROM tenant_platforms
		WHERE tenant_id = $1 AND platform = $2 AND status = 'active'
		LIMIT 1`, tenantID, platform).Scan(
		&tp.ID, &tp.TenantID, &tp.Platform, &tp.AppID,
		&tp.AppSecretHash, &tp.AppSecretEncrypted,
		&tp.Token, &tp.EncodingAESKey, &tp.WebhookURL, &tp.Status, &createdAt,
	)
	if err == sql.ErrNoRows {
		return nil, fmt.Errorf("platform config not found: tenant=%d platform=%s", tenantID, platform)
	}
	if err != nil {
		return nil, fmt.Errorf("query tenant_platforms: %w", err)
	}
	tp.CreatedAt = createdAt
	return &tp, nil
}

// DecryptAppSecret decrypts the AES-256-GCM encrypted app_secret.
func (m *Manager) DecryptAppSecret(encryptedBase64 string) (string, error) {
	ciphertext, err := base64.StdEncoding.DecodeString(encryptedBase64)
	if err != nil {
		return "", fmt.Errorf("base64 decode: %w", err)
	}

	block, err := aes.NewCipher(m.encryptionKey)
	if err != nil {
		return "", fmt.Errorf("aes new cipher: %w", err)
	}

	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return "", fmt.Errorf("gcm: %w", err)
	}

	nonceSize := gcm.NonceSize()
	if len(ciphertext) < nonceSize {
		return "", fmt.Errorf("ciphertext too short")
	}

	nonce, ciphertext := ciphertext[:nonceSize], ciphertext[nonceSize:]
	plaintext, err := gcm.Open(nil, nonce, ciphertext, nil)
	if err != nil {
		return "", fmt.Errorf("decrypt: %w", err)
	}

	return string(plaintext), nil
}

// ComputeAppSecretHash returns the SHA-256 hex hash of a secret (used for verification comparison).
func ComputeAppSecretHash(secret string) string {
	h := sha256.Sum256([]byte(secret))
	return hex.EncodeToString(h[:])
}

// EncryptAppSecret encrypts a plaintext secret using AES-256-GCM for storage.
func (m *Manager) EncryptAppSecret(secret string) (string, error) {
	block, err := aes.NewCipher(m.encryptionKey)
	if err != nil {
		return "", fmt.Errorf("aes new cipher: %w", err)
	}

	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return "", fmt.Errorf("gcm: %w", err)
	}

	nonce := make([]byte, gcm.NonceSize())
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
		return "", fmt.Errorf("generate nonce: %w", err)
	}

	ciphertext := gcm.Seal(nonce, nonce, []byte(secret), nil)
	return base64.StdEncoding.EncodeToString(ciphertext), nil
}

// --- AccessToken caching (doc section 7A: Redis TTL = expires_in - 60s) ---

const accessTokenKeyPrefix = "access_token:%s:%s" // access_token:platform:id

// GetCachedAccessToken retrieves cached access_token from Redis.
func (m *Manager) GetCachedAccessToken(ctx context.Context, platform, appID string) (string, error) {
	key := fmt.Sprintf(accessTokenKeyPrefix, platform, appID)
	return m.redis.Get(ctx, key)
}

// CacheAccessToken stores access_token in Redis with TTL = expiresIn - 60s.
func (m *Manager) CacheAccessToken(ctx context.Context, platform, appID, token string, expiresIn int) error {
	key := fmt.Sprintf(accessTokenKeyPrefix, platform, appID)
	ttl := time.Duration(expiresIn-60) * time.Second
	if ttl <= 0 {
		ttl = 60 * time.Second
	}
	return m.redis.Set(ctx, key, token, ttl)
}

// --- Security logging and alerting (doc section 7.2) ---

// SecurityLogEntry is logged when webhook verification fails.
type SecurityLogEntry struct {
	TenantID string `json:"tenant_id"`
	Platform string `json:"platform"`
	IP       string `json:"ip"`
	Reason   string `json:"reason"`
	Time     string `json:"time"`
}

// LogSecurityFailure logs a webhook verification failure.
func (m *Manager) LogSecurityFailure(ctx context.Context, tenantID, platform, ip, reason string) {
	entry := SecurityLogEntry{
		TenantID: tenantID,
		Platform: platform,
		IP:       ip,
		Reason:   reason,
		Time:     time.Now().UTC().Format(time.RFC3339),
	}
	data, _ := json.Marshal(entry)
	log.Printf("[SECURITY] %s", string(data))

	// Check consecutive failures and trigger alert if >= 10 (doc section 7.2)
	count, err := m.incrementFailCount(ctx, tenantID, platform)
	if err != nil {
		log.Printf("[SECURITY] failed to increment fail count: %v", err)
		return
	}
	if count >= 10 {
		m.sendAlert(ctx, entry, count)
	}
}

// consecutiveFailKey returns the Redis key for tracking consecutive verification failures.
func consecutiveFailKey(tenantID, platform string) string {
	return fmt.Sprintf("webhook_fail:%s:%s", tenantID, platform)
}

func (m *Manager) incrementFailCount(ctx context.Context, tenantID, platform string) (int64, error) {
	key := consecutiveFailKey(tenantID, platform)
	// Use a simplified approach: store count as a JSON number in Redis
	var count int64
	data, err := m.redis.Get(ctx, key)
	if err == nil && data != "" {
		json.Unmarshal([]byte(data), &count)
	}
	count++
	if err := m.redis.Set(ctx, key, count, 10*time.Minute); err != nil {
		return 0, err
	}
	return count, nil
}

// ResetFailCount resets the consecutive failure counter on successful verification.
func (m *Manager) ResetFailCount(ctx context.Context, tenantID, platform string) {
	key := consecutiveFailKey(tenantID, platform)
	m.redis.Delete(ctx, key)
}

func (m *Manager) sendAlert(ctx context.Context, entry SecurityLogEntry, count int64) {
	if m.alertWebhookURL == "" {
		return
	}
	payload := map[string]interface{}{
		"alert_type":    "webhook_security",
		"severity":      "CRITICAL",
		"failure_count": count,
		"entry":         entry,
	}
	data, _ := json.Marshal(payload)
	go func() {
		resp, err := m.httpClient.Post(m.alertWebhookURL, "application/json",
			bytes.NewReader(data))
		if err != nil {
			log.Printf("[ALERT] failed to send alert: %v", err)
			return
		}
		resp.Body.Close()
		log.Printf("[ALERT] sent webhook security alert: count=%d tenant=%s platform=%s", count, entry.TenantID, entry.Platform)
	}()
}
