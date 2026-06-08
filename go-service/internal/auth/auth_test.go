package auth

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/agentos/go-service/internal/config"
	"github.com/agentos/go-service/internal/model"
	"github.com/golang-jwt/jwt/v5"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestHMACSign(t *testing.T) {
	// Known answer: compute expected value using the standard library directly
	mac := hmac.New(sha256.New, []byte("secret"))
	mac.Write([]byte("test"))
	expected := hex.EncodeToString(mac.Sum(nil))

	assert.Equal(t, expected, HMACSign("test", "secret"))
	assert.Len(t, expected, 64, "HMAC-SHA256 hex output must be 64 characters")
}

func TestHMACSignEmptyPayload(t *testing.T) {
	mac := hmac.New(sha256.New, []byte("mysecret"))
	mac.Write([]byte(""))
	expected := hex.EncodeToString(mac.Sum(nil))

	result := HMACSign("", "mysecret")
	assert.Equal(t, expected, result)
	assert.Len(t, result, 64)
	// Empty payload with a secret must still produce a valid hash
	assert.NotEmpty(t, result)
}

func TestIsWhitelisted(t *testing.T) {
	tests := []struct {
		name     string
		path     string
		expected bool
	}{
		{"/health", "/health", true},
		{"/api/v1/auth/login", "/api/v1/auth/login", true},
		{"/api/v1/auth/ (prefix match)", "/api/v1/auth/refresh", true},
		{"/api/v1/chat/message", "/api/v1/chat/message", false},
		{"empty string", "", false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.expected, IsWhitelisted(tt.path))
		})
	}
}

func TestExtractToken(t *testing.T) {
	t.Run("Authorization header Bearer token", func(t *testing.T) {
		req := httptest.NewRequest(http.MethodGet, "/test", nil)
		req.Header.Set("Authorization", "Bearer mytoken123")
		assert.Equal(t, "mytoken123", extractToken(req))
	})

	t.Run("query param token", func(t *testing.T) {
		req := httptest.NewRequest(http.MethodGet, "/test?token=querytoken456", nil)
		assert.Equal(t, "querytoken456", extractToken(req))
	})

	t.Run("neither header nor query param", func(t *testing.T) {
		req := httptest.NewRequest(http.MethodGet, "/test", nil)
		assert.Equal(t, "", extractToken(req))
	})

	t.Run("Authorization header takes priority over query param", func(t *testing.T) {
		req := httptest.NewRequest(http.MethodGet, "/test?token=queryval", nil)
		req.Header.Set("Authorization", "Bearer headerval")
		assert.Equal(t, "headerval", extractToken(req))
	})
}

func TestMiddleware_DevBypass(t *testing.T) {
	cfg := &config.Config{
		ENV:       "development",
		JWTSecret: "test-secret",
	}
	mw := Middleware(cfg)

	called := false
	handler := mw(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		called = true
		w.WriteHeader(http.StatusOK)
	}))

	req := httptest.NewRequest(http.MethodGet, "/api/v1/some-protected-route", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.True(t, called, "next handler should be called in dev mode")
	assert.Equal(t, http.StatusOK, rec.Code)
}

func TestMiddleware_WhitelistPath(t *testing.T) {
	cfg := &config.Config{
		ENV:       "production",
		JWTSecret: "test-secret",
	}
	mw := Middleware(cfg)

	called := false
	handler := mw(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		called = true
		w.WriteHeader(http.StatusOK)
	}))

	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.True(t, called, "next handler should be called for whitelisted path /health")
	assert.Equal(t, http.StatusOK, rec.Code)
}

func TestMiddleware_WhitelistPrefix(t *testing.T) {
	cfg := &config.Config{
		ENV:       "production",
		JWTSecret: "test-secret",
	}
	mw := Middleware(cfg)

	called := false
	handler := mw(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		called = true
		w.WriteHeader(http.StatusOK)
	}))

	req := httptest.NewRequest(http.MethodGet, "/api/v1/auth/login", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.True(t, called, "next handler should be called for whitelisted prefix /api/v1/auth/")
	assert.Equal(t, http.StatusOK, rec.Code)
}

func TestMiddleware_SSEToken(t *testing.T) {
	cfg := &config.Config{
		ENV:       "production",
		JWTSecret: "test-secret",
	}

	// Create a valid JWT token
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"sub": "test-user",
		"exp": time.Now().Add(time.Hour).Unix(),
	})
	tokenString, err := token.SignedString([]byte("test-secret"))
	require.NoError(t, err)

	mw := Middleware(cfg)

	called := false
	handler := mw(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		called = true
		w.WriteHeader(http.StatusOK)
	}))

	req := httptest.NewRequest(http.MethodGet, "/api/v1/chat/stream?token="+tokenString, nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.True(t, called, "handler should be called with valid SSE token")
	assert.Equal(t, http.StatusOK, rec.Code)
}

func TestMiddleware_ValidJWT(t *testing.T) {
	cfg := &config.Config{
		ENV:       "production",
		JWTSecret: "test-jwt-secret",
	}

	token := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"user_id":   "test-user",
		"tenant_id": "test-tenant",
		"sub":       "test-user",
		"exp":       time.Now().Add(time.Hour).Unix(),
	})
	tokenString, err := token.SignedString([]byte("test-jwt-secret"))
	require.NoError(t, err)

	mw := Middleware(cfg)

	var capturedUserID string
	handler := mw(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		capturedUserID = r.Header.Get("X-User-ID")
		w.WriteHeader(http.StatusOK)
	}))

	req := httptest.NewRequest(http.MethodGet, "/api/v1/protected", nil)
	req.Header.Set("Authorization", "Bearer "+tokenString)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "test-user", capturedUserID, "user_id should be extracted from JWT sub claim")
}

func TestMiddleware_ExpiredJWT(t *testing.T) {
	cfg := &config.Config{
		ENV:       "production",
		JWTSecret: "test-secret",
	}

	token := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"sub": "test-user",
		"exp": time.Now().Add(-24 * time.Hour).Unix(),
	})
	tokenString, err := token.SignedString([]byte("test-secret"))
	require.NoError(t, err)

	mw := Middleware(cfg)

	called := false
	handler := mw(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		called = true
		w.WriteHeader(http.StatusOK)
	}))

	req := httptest.NewRequest(http.MethodGet, "/api/v1/protected", nil)
	req.Header.Set("Authorization", "Bearer "+tokenString)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.False(t, called, "handler should NOT be called with expired JWT")
	assert.Equal(t, http.StatusUnauthorized, rec.Code)

	var apiResp model.APIResponse
	err = json.Unmarshal(rec.Body.Bytes(), &apiResp)
	require.NoError(t, err)
	assert.Equal(t, model.CodeUnauthorized, apiResp.Code)
}

func TestMiddleware_InvalidSignature(t *testing.T) {
	cfg := &config.Config{
		ENV:       "production",
		JWTSecret: "test-secret",
	}

	// Sign with a different secret than what the middleware expects
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"sub": "test-user",
		"exp": time.Now().Add(time.Hour).Unix(),
	})
	tokenString, err := token.SignedString([]byte("wrong-secret"))
	require.NoError(t, err)

	mw := Middleware(cfg)

	called := false
	handler := mw(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		called = true
		w.WriteHeader(http.StatusOK)
	}))

	req := httptest.NewRequest(http.MethodGet, "/api/v1/protected", nil)
	req.Header.Set("Authorization", "Bearer "+tokenString)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.False(t, called, "handler should NOT be called with invalid signature")
	assert.Equal(t, http.StatusUnauthorized, rec.Code)
}

func TestMiddleware_NoAuth(t *testing.T) {
	cfg := &config.Config{
		ENV:       "production",
		JWTSecret: "test-secret",
	}
	mw := Middleware(cfg)

	called := false
	handler := mw(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		called = true
		w.WriteHeader(http.StatusOK)
	}))

	req := httptest.NewRequest(http.MethodGet, "/api/v1/protected", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.False(t, called, "handler should NOT be called without auth")
	assert.Equal(t, http.StatusUnauthorized, rec.Code)

	var apiResp model.APIResponse
	err := json.Unmarshal(rec.Body.Bytes(), &apiResp)
	require.NoError(t, err)
	assert.Equal(t, model.CodeUnauthorized, apiResp.Code)
}

func TestMiddleware_AdminAPIKey(t *testing.T) {
	cfg := &config.Config{
		ENV:         "production",
		AdminAPIKey: "my-secret-admin-key",
	}
	mw := Middleware(cfg)

	called := false
	handler := mw(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		called = true
		w.WriteHeader(http.StatusOK)
	}))

	req := httptest.NewRequest(http.MethodGet, "/api/v1/admin/users", nil)
	req.Header.Set("X-API-Key", "my-secret-admin-key")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.True(t, called, "handler should be called with valid admin API key")
	assert.Equal(t, http.StatusOK, rec.Code)
}
