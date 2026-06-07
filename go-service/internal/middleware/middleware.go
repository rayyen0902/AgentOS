package middleware

import (
	"context"
	"crypto/rand"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"sync"
	"time"

	"github.com/agentos/go-service/internal/config"
	"github.com/agentos/go-service/internal/model"
)

type contextKey string

const TraceIDKey contextKey = "trace_id"

// ---------- RequestID ----------

func RequestID(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		traceID := r.Header.Get("X-Trace-ID")
		if traceID == "" {
			traceID = "tr_" + newUUID()
		}
		ctx := context.WithValue(r.Context(), TraceIDKey, traceID)
		w.Header().Set("X-Trace-ID", traceID)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

func GetTraceID(ctx context.Context) string {
	if v, ok := ctx.Value(TraceIDKey).(string); ok {
		return v
	}
	return ""
}

func newUUID() string {
	b := make([]byte, 16)
	rand.Read(b)
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:16])
}

// ---------- Logger ----------

func Logger(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		sw := &statusWriter{ResponseWriter: w, status: 200}
		next.ServeHTTP(sw, r)
		traceID := GetTraceID(r.Context())
		log.Printf(`{"trace_id":"%s","method":"%s","path":"%s","status":%d,"duration_ms":%d}`,
			traceID, r.Method, r.URL.Path, sw.status, time.Since(start).Milliseconds())
	})
}

type statusWriter struct {
	http.ResponseWriter
	status int
}

func (sw *statusWriter) WriteHeader(code int) {
	sw.status = code
	sw.ResponseWriter.WriteHeader(code)
}

// ---------- Recovery ----------

func Recovery(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if rec := recover(); rec != nil {
				log.Printf("PANIC: %v", rec)
				WriteJSON(w, model.CodeInternalError, model.NewErrorResponse(
					model.CodeInternalError, "internal server error", GetTraceID(r.Context())))
			}
		}()
		next.ServeHTTP(w, r)
	})
}

// ---------- RateLimit (token bucket) ----------

func RateLimit(cfg *config.Config) func(http.Handler) http.Handler {
	global := newTokenBucket(cfg.RateLimitGlobal)
	users := newUserBucket(cfg.RateLimitUserMsg)

	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if !global.allow() {
				WriteJSON(w, model.CodeRateLimited, model.NewErrorResponse(model.CodeRateLimited, "global rate limit exceeded", GetTraceID(r.Context())))
				return
			}
			userID := r.Header.Get("X-User-ID")
			if userID != "" && !users.allow(userID) {
				WriteJSON(w, model.CodeRateLimited, model.NewErrorResponse(model.CodeRateLimited, "user rate limit exceeded", GetTraceID(r.Context())))
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}

// ---------- JSON helpers ----------

func WriteJSON(w http.ResponseWriter, errCode int, resp model.APIResponse) {
	httpStatus := model.HTTPStatus(errCode)
	if errCode != 0 {
		httpStatus = model.HTTPStatus(errCode)
	} else {
		httpStatus = 200
	}
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(httpStatus)
	json.NewEncoder(w).Encode(resp)
}

// ---------- token bucket ----------

type tokenBucket struct {
	rate   int
	tokens float64
	last   time.Time
	mu     sync.Mutex
}

func newTokenBucket(ratePerMin int) *tokenBucket {
	return &tokenBucket{rate: ratePerMin, tokens: float64(ratePerMin), last: time.Now()}
}

func (tb *tokenBucket) allow() bool {
	tb.mu.Lock()
	defer tb.mu.Unlock()
	now := time.Now()
	elapsed := now.Sub(tb.last).Minutes()
	tb.tokens += elapsed * float64(tb.rate)
	if tb.tokens > float64(tb.rate) {
		tb.tokens = float64(tb.rate)
	}
	tb.last = now
	if tb.tokens < 1 {
		return false
	}
	tb.tokens--
	return true
}

type userBucket struct {
	rate  int
	users map[string]*tokenBucket
	mu    sync.Mutex
}

func newUserBucket(ratePerMin int) *userBucket {
	return &userBucket{rate: ratePerMin, users: make(map[string]*tokenBucket)}
}

func (ub *userBucket) allow(userID string) bool {
	ub.mu.Lock()
	tb, ok := ub.users[userID]
	if !ok {
		tb = newTokenBucket(ub.rate)
		ub.users[userID] = tb
	}
	ub.mu.Unlock()
	return tb.allow()
}
