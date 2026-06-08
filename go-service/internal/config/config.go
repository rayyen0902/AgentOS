package config

import (
	"encoding/hex"
	"fmt"
	"log"
	"os"
	"strconv"
	"time"
)

type Config struct {
	Port        string
	ENV         string
	AdminAPIKey string

	DatabaseURL string
	RedisURL    string

	PythonServiceURL     string
	PythonServiceTimeout time.Duration

	JWTSecret string
	JWTExpire time.Duration

	RateLimitGlobal  int
	RateLimitUserMsg int

	PlatformSecretEncryptionKey string
	AlertWebhookURL             string
}

func Load() (*Config, error) {
	cfg := &Config{
		Port:        getEnv("PORT", "8080"),
		ENV:         getEnv("ENV", "development"),
		AdminAPIKey: getEnv("ADMIN_API_KEY", ""),

		DatabaseURL: getEnv("DATABASE_URL", ""),
		RedisURL:    getEnv("REDIS_URL", ""),

		PythonServiceURL:     getEnv("PYTHON_SERVICE_URL", "http://localhost:8000"),
		PythonServiceTimeout: getDurationEnv("PYTHON_SERVICE_TIMEOUT", 35*time.Second),

		JWTSecret: getEnv("JWT_SECRET", ""),
		JWTExpire: getDurationEnv("JWT_EXPIRE", 24*time.Hour),

		RateLimitGlobal:  getIntEnv("RATE_LIMIT_GLOBAL", 1000),
		RateLimitUserMsg: getIntEnv("RATE_LIMIT_USER_MSG", 60),

		PlatformSecretEncryptionKey: getEnv("PLATFORM_SECRET_ENCRYPTION_KEY", ""),
		AlertWebhookURL:             getEnv("ALERT_WEBHOOK_URL", ""),
	}

	if err := cfg.validate(); err != nil {
		return nil, fmt.Errorf("config validation: %w", err)
	}

	return cfg, nil
}

func (c *Config) validate() error {
	if c.DatabaseURL == "" {
		return fmt.Errorf("DATABASE_URL is required")
	}
	if c.RedisURL == "" {
		return fmt.Errorf("REDIS_URL is required")
	}
	if c.JWTSecret == "" {
		return fmt.Errorf("JWT_SECRET is required")
	}
	if c.AdminAPIKey == "" {
		return fmt.Errorf("ADMIN_API_KEY is required")
	}
	if c.PlatformSecretEncryptionKey == "" {
		return fmt.Errorf("PLATFORM_SECRET_ENCRYPTION_KEY is required")
	}
	// S1-08: AES-256 要求 key 32 bytes（支持 hex 编码 64-char 或 raw 32-byte）
	keyBytes, err := hex.DecodeString(c.PlatformSecretEncryptionKey)
	if err != nil {
		// hex 解码失败→视为 raw bytes
		keyBytes = []byte(c.PlatformSecretEncryptionKey)
	}
	if len(keyBytes) != 32 {
		panic(fmt.Sprintf("PLATFORM_SECRET_ENCRYPTION_KEY must be a 32-byte AES-256 key (hex-encoded 64 chars or raw 32 bytes), got %d bytes", len(keyBytes)))
	}
	validEnvs := map[string]bool{"production": true, "staging": true, "development": true}
	if !validEnvs[c.ENV] {
		return fmt.Errorf("ENV must be one of production|staging|development, got: %s", c.ENV)
	}
	return nil
}

func getEnv(key, defaultVal string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return defaultVal
}

func getIntEnv(key string, defaultVal int) int {
	if v := os.Getenv(key); v != "" {
		n, err := strconv.Atoi(v)
		if err == nil {
			return n
		}
		log.Printf("[WARN] config: %s=%q cannot be parsed as int, using default %d: %v", key, v, defaultVal, err)
	}
	return defaultVal
}

func getDurationEnv(key string, defaultVal time.Duration) time.Duration {
	if v := os.Getenv(key); v != "" {
		d, err := time.ParseDuration(v)
		if err == nil {
			return d
		}
		log.Printf("[WARN] config: %s=%q cannot be parsed as duration, using default %v: %v", key, v, defaultVal, err)
	}
	return defaultVal
}
