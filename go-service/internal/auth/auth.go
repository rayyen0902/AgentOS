package auth

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"strings"

	"github.com/agentos/go-service/internal/config"
	"github.com/agentos/go-service/internal/middleware"
	"github.com/agentos/go-service/internal/model"
	"github.com/golang-jwt/jwt/v5"
)

var authWhitelist = []string{"/health", "/api/v1/auth/", "/api/v1/webhook/"}

func Middleware(cfg *config.Config) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			path := r.URL.Path
			for _, pfx := range authWhitelist {
				if strings.HasPrefix(path, pfx) {
					next.ServeHTTP(w, r)
					return
				}
			}

			// Dev mode: skip auth for all routes
			if cfg.ENV == "development" {
				next.ServeHTTP(w, r)
				return
			}

			// S3-03: SSE endpoint supports query param token for EventSource compatibility.
			if path == "/api/v1/chat/stream" {
				tokenStr := r.URL.Query().Get("token")
				if tokenStr != "" {
					r.Header.Set("Authorization", "Bearer "+tokenStr)
				}
			}

			// API Key for admin endpoints
			if strings.HasPrefix(path, "/api/v1/admin/") {
				key := r.Header.Get("X-API-Key")
				if key == "" {
					key = r.URL.Query().Get("api_key")
				}
				if key != cfg.AdminAPIKey {
					middleware.WriteJSON(w, model.CodeAPIKeyInvalid,
						model.NewErrorResponse(model.CodeAPIKeyInvalid, "invalid api key", middleware.GetTraceID(r.Context())))
					return
				}
				next.ServeHTTP(w, r)
				return
			}

			// JWT auth for other endpoints
			tokenStr := extractToken(r)
			if tokenStr == "" {
				middleware.WriteJSON(w, model.CodeUnauthorized,
					model.NewErrorResponse(model.CodeUnauthorized, "missing or invalid token", middleware.GetTraceID(r.Context())))
				return
			}
			claims := &jwt.RegisteredClaims{}
			token, err := jwt.ParseWithClaims(tokenStr, claims, func(t *jwt.Token) (interface{}, error) {
				return []byte(cfg.JWTSecret), nil
			})
			if err != nil || !token.Valid {
				middleware.WriteJSON(w, model.CodeUnauthorized,
					model.NewErrorResponse(model.CodeUnauthorized, "token invalid or expired", middleware.GetTraceID(r.Context())))
				return
			}
			if claims.Subject != "" {
				r.Header.Set("X-User-ID", claims.Subject)
			}
			next.ServeHTTP(w, r)
		})
	}
}

// extractToken gets the JWT from Authorization header or query param ?token=.
func extractToken(r *http.Request) string {
	// Header first
	authHeader := r.Header.Get("Authorization")
	if authHeader != "" && strings.HasPrefix(authHeader, "Bearer ") {
		return strings.TrimPrefix(authHeader, "Bearer ")
	}
	// Fallback: query param (needed for EventSource SSE)
	return r.URL.Query().Get("token")
}

// HMACSign computes HMAC-SHA256 hex signature.
func HMACSign(payload, secret string) string {
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(payload))
	return hex.EncodeToString(mac.Sum(nil))
}

// IsWhitelisted returns true if the path doesn't need auth.
func IsWhitelisted(path string) bool {
	for _, pfx := range authWhitelist {
		if strings.HasPrefix(path, pfx) {
			return true
		}
	}
	return false
}
