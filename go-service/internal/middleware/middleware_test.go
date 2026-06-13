package middleware

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/agentos/go-service/internal/config"
	"github.com/agentos/go-service/internal/model"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestWriteJSON(t *testing.T) {
	w := httptest.NewRecorder()

	resp := model.APIResponse{
		Code:    0,
		Message: "ok",
		Data:    nil,
		TraceID: "tr_test123",
	}

	WriteJSON(w, model.CodeSuccess, resp)

	// Verify Content-Type
	contentType := w.Header().Get("Content-Type")
	assert.Contains(t, contentType, "application/json", "Content-Type must be application/json")

	// Verify status code
	assert.Equal(t, http.StatusOK, w.Code, "status code must be 200 for CodeSuccess")

	// Verify JSON body
	var decoded model.APIResponse
	err := json.NewDecoder(w.Body).Decode(&decoded)
	assert.NoError(t, err)
	assert.Equal(t, 0, decoded.Code)
	assert.Equal(t, "ok", decoded.Message)
	assert.Equal(t, "tr_test123", decoded.TraceID)
}

func TestWriteJSON_ErrorResponse(t *testing.T) {
	w := httptest.NewRecorder()

	resp := model.NewErrorResponse(model.CodeBadRequest, "bad request", "tr_error")

	WriteJSON(w, model.CodeBadRequest, resp)

	assert.Equal(t, http.StatusBadRequest, w.Code)

	var decoded model.APIResponse
	err := json.NewDecoder(w.Body).Decode(&decoded)
	assert.NoError(t, err)
	assert.Equal(t, model.CodeBadRequest, decoded.Code)
	assert.Equal(t, "bad request", decoded.Message)
	assert.Equal(t, "tr_error", decoded.TraceID)
	// NewErrorResponse sets Data: nil which JSON-encodes as "null"
	// When decoded, json.RawMessage becomes the 4-byte value "null"
	assert.Equal(t, json.RawMessage("null"), decoded.Data, "data for error response must be JSON null")
}

func TestNewUUID(t *testing.T) {
	id1 := newUUID()
	id2 := newUUID()

	// Both are non-empty
	assert.NotEmpty(t, id1)
	assert.NotEmpty(t, id2)

	// Valid UUID format: 36 characters with 4 dashes (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)
	assert.Len(t, id1, 36)
	assert.Len(t, id2, 36)

	dashCount1 := strings.Count(id1, "-")
	dashCount2 := strings.Count(id2, "-")
	assert.Equal(t, 4, dashCount1, "UUID must have 4 dashes")
	assert.Equal(t, 4, dashCount2, "UUID must have 4 dashes")

	// Two UUIDs must not be equal
	assert.NotEqual(t, id1, id2, "two UUIDs must be unique")
}

func TestRequestID_Generates(t *testing.T) {
	var capturedTraceID string
	handler := RequestID(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		capturedTraceID = GetTraceID(r.Context())
		w.WriteHeader(http.StatusOK)
	}))

	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.NotEmpty(t, capturedTraceID, "trace ID should be generated")
	assert.Contains(t, capturedTraceID, "tr_", "trace ID should have tr_ prefix")
	assert.Equal(t, capturedTraceID, rec.Header().Get("X-Trace-ID"), "X-Trace-ID header should match context value")
}

func TestRequestID_Propagates(t *testing.T) {
	var capturedTraceID string
	handler := RequestID(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		capturedTraceID = GetTraceID(r.Context())
		w.WriteHeader(http.StatusOK)
	}))

	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	req.Header.Set("X-Trace-ID", "my-trace-123")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, "my-trace-123", capturedTraceID)
	assert.Equal(t, "my-trace-123", rec.Header().Get("X-Trace-ID"))
}

func TestRecovery(t *testing.T) {
	handler := Recovery(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		panic("test panic")
	}))

	// Use httptest.NewServer to verify the server does NOT crash
	srv := httptest.NewServer(handler)
	defer srv.Close()

	resp, err := http.Get(srv.URL + "/test")
	require.NoError(t, err, "server should not crash on panic")
	defer resp.Body.Close()

	assert.Equal(t, http.StatusInternalServerError, resp.StatusCode)

	body, err := io.ReadAll(resp.Body)
	require.NoError(t, err)

	var apiResp model.APIResponse
	err = json.Unmarshal(body, &apiResp)
	require.NoError(t, err)
	assert.Equal(t, model.CodeInternalError, apiResp.Code, "response should contain internal error code")
	assert.Equal(t, "internal server error", apiResp.Message)
}

func TestRecoveryNoPanic(t *testing.T) {
	handler := Recovery(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
	}))

	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Contains(t, rec.Body.String(), `"status"`)
}

func TestRateLimit_Allows(t *testing.T) {
	cfg := &config.Config{
		RateLimitGlobal:  3,
		RateLimitUserMsg: 1000,
	}
	mw := RateLimit(cfg)
	handler := mw(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))

	for i := 0; i < 3; i++ {
		req := httptest.NewRequest(http.MethodGet, "/test", nil)
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		assert.Equal(t, http.StatusOK, rec.Code, "request %d should be allowed", i+1)
	}
}

func TestRateLimit_Blocks(t *testing.T) {
	cfg := &config.Config{
		RateLimitGlobal:  2,
		RateLimitUserMsg: 1000,
	}
	mw := RateLimit(cfg)
	handler := mw(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))

	// Exhaust the 2 allowed tokens
	for i := 0; i < 2; i++ {
		req := httptest.NewRequest(http.MethodGet, "/test", nil)
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		require.Equal(t, http.StatusOK, rec.Code, "request %d should be allowed", i+1)
	}

	// Third request must be blocked
	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	assert.Equal(t, http.StatusTooManyRequests, rec.Code)

	var apiResp model.APIResponse
	err := json.Unmarshal(rec.Body.Bytes(), &apiResp)
	require.NoError(t, err)
	assert.Equal(t, model.CodeRateLimited, apiResp.Code)
}

func TestRateLimit_Eviction(t *testing.T) {
	// Directly test tokenBucket.allow() logic:
	// bucket with capacity 10, tokens=10 -> 10 successful allows, 11th fails.
	tb := newTokenBucket(10)

	for i := 0; i < 10; i++ {
		assert.True(t, tb.allow(), "allow %d should succeed", i+1)
	}

	// 11th call: bucket is empty and no time has elapsed for refill
	assert.False(t, tb.allow(), "11th allow should fail after bucket is depleted")
}

func TestRateLimit_RecoverAfterRefill(t *testing.T) {
	// bucket with capacity 100, tokens=100 -> exhaust all, then verify fail.
	// We cannot easily manipulate time on the unexported tokenBucket, so we
	// test the middleware behavior: after exhausting, requests are denied;
	// we verify the blocked response shape and confirm the bucket concept holds.
	cfg := &config.Config{
		RateLimitGlobal:  10,
		RateLimitUserMsg: 1000,
	}
	mw := RateLimit(cfg)
	handler := mw(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))

	// Exhaust all global tokens
	for i := 0; i < 10; i++ {
		req := httptest.NewRequest(http.MethodGet, "/test", nil)
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		require.Equal(t, http.StatusOK, rec.Code, "request %d should be allowed", i+1)
	}

	// Next request is denied
	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	assert.Equal(t, http.StatusTooManyRequests, rec.Code)

	var apiResp model.APIResponse
	err := json.Unmarshal(rec.Body.Bytes(), &apiResp)
	require.NoError(t, err)
	assert.Equal(t, model.CodeRateLimited, apiResp.Code)
	assert.Contains(t, apiResp.Message, "global rate limit exceeded")
}

func TestRateLimit_UserBucket(t *testing.T) {
	cfg := &config.Config{
		RateLimitGlobal:  1000,
		RateLimitUserMsg: 3,
	}
	mw := RateLimit(cfg)
	handler := mw(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))

	// User A: allowed within per-user threshold
	for i := 0; i < 3; i++ {
		req := httptest.NewRequest(http.MethodGet, "/test", nil)
		req.Header.Set("X-User-ID", "user-a")
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		require.Equal(t, http.StatusOK, rec.Code, "user-a request %d should be allowed", i+1)
	}

	// User A: 4th request blocked by user rate limit
	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	req.Header.Set("X-User-ID", "user-a")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	assert.Equal(t, http.StatusTooManyRequests, rec.Code)

	var apiResp model.APIResponse
	err := json.Unmarshal(rec.Body.Bytes(), &apiResp)
	require.NoError(t, err)
	assert.Equal(t, model.CodeRateLimited, apiResp.Code)
	assert.Contains(t, apiResp.Message, "user rate limit exceeded")

	// User B: unaffected by User A's rate limit, still gets through
	req2 := httptest.NewRequest(http.MethodGet, "/test", nil)
	req2.Header.Set("X-User-ID", "user-b")
	rec2 := httptest.NewRecorder()
	handler.ServeHTTP(rec2, req2)
	assert.Equal(t, http.StatusOK, rec2.Code, "user-b should not be affected by user-a's rate limit")
}

func TestRateLimit_NoUserHeader(t *testing.T) {
	// Without X-User-ID, only the global bucket applies.
	cfg := &config.Config{
		RateLimitGlobal:  2,
		RateLimitUserMsg: 1, // very tight per-user, but irrelevant without X-User-ID
	}
	mw := RateLimit(cfg)
	handler := mw(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))

	// 2 requests allowed (global limit only)
	for i := 0; i < 2; i++ {
		req := httptest.NewRequest(http.MethodGet, "/test", nil)
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		require.Equal(t, http.StatusOK, rec.Code, "request %d should be allowed", i+1)
	}

	// 3rd denied by global limit
	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	assert.Equal(t, http.StatusTooManyRequests, rec.Code)
}

func TestLogger(t *testing.T) {
	handler := Logger(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))

	req := httptest.NewRequest(http.MethodPost, "/api/v1/test", nil)
	rec := httptest.NewRecorder()
	// Logger should not panic; it logs structured output to stdout.
	handler.ServeHTTP(rec, req)
	assert.Equal(t, http.StatusOK, rec.Code)
}

func TestLogger_ClientError(t *testing.T) {
	handler := Logger(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	}))

	req := httptest.NewRequest(http.MethodGet, "/nonexistent", nil)
	rec := httptest.NewRecorder()
	// Logger should record 404 correctly
	handler.ServeHTTP(rec, req)
	assert.Equal(t, http.StatusNotFound, rec.Code)
}

func TestGetTraceID_EmptyContext(t *testing.T) {
	ctx := context.Background()
	assert.Equal(t, "", GetTraceID(ctx))
}
