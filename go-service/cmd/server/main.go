package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/agentos/go-service/internal/auth"
	"github.com/agentos/go-service/internal/config"
	"github.com/agentos/go-service/internal/db"
	"github.com/agentos/go-service/internal/handler"
	"github.com/agentos/go-service/internal/middleware"
	"github.com/agentos/go-service/internal/platform"
	redisutil "github.com/agentos/go-service/internal/redis"
	"github.com/agentos/go-service/internal/session"
	"github.com/agentos/go-service/internal/sse"
)

func main() {
	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("config: %v", err)
	}

	pg, err := db.New(cfg.DatabaseURL)
	if err != nil {
		log.Fatalf("database: %v", err)
	}
	defer pg.Close()
	log.Println("[OK] PostgreSQL connected, pgvector enabled")

	redis, err := redisutil.New(cfg.RedisURL)
	if err != nil {
		log.Fatalf("redis: %v", err)
	}
	defer redis.Close()
	log.Println("[OK] Redis connected, PING=PONG")

	// --- Initialize platform manager and adapters (Step 7) ---
	platformMgr := platform.NewManager(
		pg,
		redis,
		cfg.PlatformSecretEncryptionKey,
		cfg.AlertWebhookURL,
	)
	log.Println("[OK] Platform manager initialized")

	sessionMgr := session.NewManager(redis)
	sseBroker := sse.NewBroker()
	h := handler.NewWithPlatforms(cfg, sessionMgr, sseBroker, redis, platformMgr)
	log.Println("[OK] Platform adapters: WeCom, Douyin, XHS")

	mux := http.NewServeMux()

	// --- Health ---
	mux.HandleFunc("GET /health", handler.Health)

	// --- Auth ---
	mux.HandleFunc("POST /api/v1/auth/register", handler.Register)
	mux.HandleFunc("POST /api/v1/auth/login", handler.Login)
	mux.HandleFunc("POST /api/v1/auth/send-code", handler.SendCode)

	// --- Chat ---
	mux.HandleFunc("POST /api/v1/chat/message", h.ChatMessage)
	mux.HandleFunc("GET /api/v1/chat/stream", h.ChatStream)

	// --- Webhooks (Step 7: platform adapters) ---
	// Each platform webhook supports GET (URL verification) and POST (message receive)
	mux.HandleFunc("GET /api/v1/webhook/wecom/{tenant_id}", h.WebhookHandler)
	mux.HandleFunc("POST /api/v1/webhook/wecom/{tenant_id}", h.WebhookHandler)
	mux.HandleFunc("GET /api/v1/webhook/douyin/{tenant_id}", h.WebhookHandler)
	mux.HandleFunc("POST /api/v1/webhook/douyin/{tenant_id}", h.WebhookHandler)
	mux.HandleFunc("GET /api/v1/webhook/xhs/{tenant_id}", h.WebhookHandler)
	mux.HandleFunc("POST /api/v1/webhook/xhs/{tenant_id}", h.WebhookHandler)

	// --- Admin ---
	mux.HandleFunc("GET /api/v1/admin/tenants", handler.ListTenants)
	mux.HandleFunc("PUT /api/v1/admin/tenants/{id}/approve", handler.ApproveTenant)
	mux.HandleFunc("GET /api/v1/admin/tenants/{id}", handler.GetTenant)

	// --- Middleware chain ---
	// Wrapping order: Recovery → RequestID → Logger → RateLimit → Auth → mux
	// Outermost middleware runs first on inbound request, last on outbound response.
	var httpHandler http.Handler = mux
	httpHandler = auth.Middleware(cfg)(httpHandler)
	rateLimitMw, rateLimitCleanup := middleware.RateLimitWithCleanup(cfg)
	defer rateLimitCleanup()
	httpHandler = rateLimitMw(httpHandler)
	httpHandler = middleware.Logger(httpHandler)
	httpHandler = middleware.RequestID(httpHandler)
	httpHandler = middleware.Recovery(httpHandler)

	srv := &http.Server{
		Addr:         ":" + cfg.Port,
		Handler:      httpHandler,
		ReadTimeout:  30 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  120 * time.Second,
	}

	go func() {
		log.Printf("Go service listening on :%s [%s]", cfg.Port, cfg.ENV)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("server: %v", err)
		}
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit
	log.Println("Shutting down...")
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	srv.Shutdown(ctx)
}
