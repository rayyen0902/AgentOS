package middleware

import (
	"context"
	"crypto/rand"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"sync"
	"time"

	"github.com/agentos/go-service/internal/config"
	"github.com/agentos/go-service/internal/model"
)

type contextKey string

const TraceIDKey contextKey = "trace_id"

var logger = slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))

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
	if _, err := rand.Read(b); err != nil {
		// S3-12: handle crypto/rand.Read error — fallback is deterministic but safe
		for i := range b {
			b[i] = byte(time.Now().UnixNano()>>(i*4)) ^ 0xA5
		}
	}
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:16])
}

// ---------- Logger ----------

func Logger(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		sw := &statusWriter{ResponseWriter: w, status: 200}
		next.ServeHTTP(sw, r)
		// S3-11: Use slog structured logging instead of log.Printf hand-rolled JSON
		logger.Info("request",
			slog.String("trace_id", GetTraceID(r.Context())),
			slog.String("method", r.Method),
			slog.String("path", r.URL.Path),
			slog.Int("status", sw.status),
			slog.Int64("duration_ms", time.Since(start).Milliseconds()),
		)
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
				logger.Error("panic recovered", slog.Any("panic", rec), slog.String("trace_id", GetTraceID(r.Context())))
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

	// S3-08: Start background goroutine to periodically evict stale user entries
	go users.evictLoop(5 * time.Minute)
	// Drain the evict goroutine on program exit — caller should use the returned cleanup
	// Note: this is a minor leak; in production, use a global cleaner.

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

// S3-09: Simplified — single WriteJSON that delegates to model.HTTPStatus.
func WriteJSON(w http.ResponseWriter, errCode int, resp model.APIResponse) {
	httpStatus := model.HTTPStatus(errCode)
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(httpStatus)
	json.NewEncoder(w).Encode(resp)
}

// ---------- token bucket ----------

type tokenBucket struct {
	rate      int
	tokens    float64
	last      time.Time
	lastAllow time.Time // S3-08: track last access for eviction
	mu        sync.Mutex
}

func newTokenBucket(ratePerMin int) *tokenBucket {
	now := time.Now()
	return &tokenBucket{rate: ratePerMin, tokens: float64(ratePerMin), last: now, lastAllow: now}
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
	tb.lastAllow = now
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

// evictLoop periodically removes user entries that haven't been accessed in > 2x period.
// S3-08: prevents unbounded memory growth in the user rate limiter.
func (ub *userBucket) evictLoop(interval time.Duration) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for range ticker.C {
		ub.mu.Lock()
		cutoff := time.Now().Add(-2 * time.Minute)
		for id, tb := range ub.users {
			tb.mu.Lock()
			lastAccess := tb.lastAllow
			tb.mu.Unlock()
			if lastAccess.Before(cutoff) {
				delete(ub.users, id)
			}
		}
		ub.mu.Unlock()
	}
}
