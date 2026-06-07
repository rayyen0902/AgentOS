package config

import (
	"fmt"
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
	}
	return defaultVal
}

func getDurationEnv(key string, defaultVal time.Duration) time.Duration {
	if v := os.Getenv(key); v != "" {
		d, err := time.ParseDuration(v)
		if err == nil {
			return d
		}
	}
	return defaultVal
}
