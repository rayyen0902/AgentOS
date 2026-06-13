package config

import (
	"os"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

// unsetTestEnvs removes any env vars that config.Load() reads, so tests start clean.
func unsetTestEnvs(t *testing.T) {
	t.Helper()
	vars := []string{
		"PORT", "ENV", "ADMIN_API_KEY",
		"DATABASE_URL", "REDIS_URL",
		"PYTHON_SERVICE_URL", "PYTHON_SERVICE_TIMEOUT",
		"JWT_SECRET", "JWT_EXPIRE",
		"RATE_LIMIT_GLOBAL", "RATE_LIMIT_USER_MSG",
		"PLATFORM_SECRET_ENCRYPTION_KEY", "ALERT_WEBHOOK_URL",
	}
	for _, v := range vars {
		os.Unsetenv(v)
	}
}

// setRequiredEnvs sets the minimum env vars needed for a valid config.
func setRequiredEnvs(t *testing.T) {
	t.Helper()
	os.Setenv("DATABASE_URL", "postgres://localhost:5432/test")
	os.Setenv("REDIS_URL", "localhost:6379")
	os.Setenv("JWT_SECRET", "my-jwt-secret")
	os.Setenv("ADMIN_API_KEY", "admin-key-123")
	os.Setenv("PLATFORM_SECRET_ENCRYPTION_KEY", "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
}

func TestLoad_Defaults(t *testing.T) {
	unsetTestEnvs(t)
	setRequiredEnvs(t)

	cfg, err := Load()
	assert.NoError(t, err)
	assert.NotNil(t, cfg)

	assert.Equal(t, "8080", cfg.Port)
	assert.Equal(t, "development", cfg.ENV)
	assert.Equal(t, "admin-key-123", cfg.AdminAPIKey)

	assert.Equal(t, "postgres://localhost:5432/test", cfg.DatabaseURL)
	assert.Equal(t, "localhost:6379", cfg.RedisURL)

	assert.Equal(t, "http://localhost:8000", cfg.PythonServiceURL)
	assert.Equal(t, 35*time.Second, cfg.PythonServiceTimeout)

	assert.Equal(t, "my-jwt-secret", cfg.JWTSecret)
	assert.Equal(t, 24*time.Hour, cfg.JWTExpire)

	assert.Equal(t, 1000, cfg.RateLimitGlobal)
	assert.Equal(t, 60, cfg.RateLimitUserMsg)

	assert.Equal(t, "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f", cfg.PlatformSecretEncryptionKey)
	assert.Equal(t, "", cfg.AlertWebhookURL)
}


func TestLoad_EnvOverrides(t *testing.T) {
	unsetTestEnvs(t)
	setRequiredEnvs(t)

	os.Setenv("PORT", "9090")
	os.Setenv("ENV", "staging")
	os.Setenv("PYTHON_SERVICE_URL", "http://py:9000")
	os.Setenv("PYTHON_SERVICE_TIMEOUT", "10s")
	os.Setenv("JWT_EXPIRE", "1h")
	os.Setenv("RATE_LIMIT_GLOBAL", "500")
	os.Setenv("RATE_LIMIT_USER_MSG", "30")
	os.Setenv("ALERT_WEBHOOK_URL", "https://hooks.example.com/alert")

	cfg, err := Load()
	assert.NoError(t, err)
	assert.NotNil(t, cfg)

	assert.Equal(t, "9090", cfg.Port)
	assert.Equal(t, "staging", cfg.ENV)
	assert.Equal(t, "http://py:9000", cfg.PythonServiceURL)

	// time.Duration comparisons need the same type
	expectedTimeout := mustParseDuration(t, "10s")
	assert.Equal(t, expectedTimeout, cfg.PythonServiceTimeout)

	expectedExpire := mustParseDuration(t, "1h")
	assert.Equal(t, expectedExpire, cfg.JWTExpire)

	assert.Equal(t, 500, cfg.RateLimitGlobal)
	assert.Equal(t, 30, cfg.RateLimitUserMsg)
	assert.Equal(t, "https://hooks.example.com/alert", cfg.AlertWebhookURL)
}

func TestLoad_MissingDatabaseURL(t *testing.T) {
	unsetTestEnvs(t)
	setRequiredEnvs(t)
	os.Unsetenv("DATABASE_URL")

	cfg, err := Load()
	assert.Nil(t, cfg)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "DATABASE_URL is required")
}

func TestLoad_MissingRedisURL(t *testing.T) {
	unsetTestEnvs(t)
	setRequiredEnvs(t)
	os.Unsetenv("REDIS_URL")

	cfg, err := Load()
	assert.Nil(t, cfg)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "REDIS_URL is required")
}

func TestLoad_MissingJWTSecret(t *testing.T) {
	unsetTestEnvs(t)
	setRequiredEnvs(t)
	os.Unsetenv("JWT_SECRET")

	cfg, err := Load()
	assert.Nil(t, cfg)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "JWT_SECRET is required")
}

func TestLoad_MissingAdminAPIKey(t *testing.T) {
	unsetTestEnvs(t)
	setRequiredEnvs(t)
	os.Unsetenv("ADMIN_API_KEY")

	cfg, err := Load()
	assert.Nil(t, cfg)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "ADMIN_API_KEY is required")
}

func TestLoad_MissingPlatformSecretEncryptionKey(t *testing.T) {
	unsetTestEnvs(t)
	setRequiredEnvs(t)
	os.Unsetenv("PLATFORM_SECRET_ENCRYPTION_KEY")

	cfg, err := Load()
	assert.Nil(t, cfg)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "PLATFORM_SECRET_ENCRYPTION_KEY is required")
}

func TestLoad_InvalidEnv(t *testing.T) {
	unsetTestEnvs(t)
	setRequiredEnvs(t)
	os.Setenv("ENV", "invalid-env")

	cfg, err := Load()
	assert.Nil(t, cfg)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "ENV must be one of production|staging|development")
}

func TestLoad_InvalidENVValue(t *testing.T) {
	unsetTestEnvs(t)
	setRequiredEnvs(t)
	os.Setenv("ENV", "testing")

	cfg, err := Load()
	assert.Nil(t, cfg)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "ENV must be one of")
}

func TestLoad_InvalidEncryptionKeyLength_TooShort(t *testing.T) {
	unsetTestEnvs(t)
	setRequiredEnvs(t)
	// 16 hex bytes decoded = 8 raw bytes, less than required 32
	os.Setenv("PLATFORM_SECRET_ENCRYPTION_KEY", "000102030405060708090a0b0c0d0e0f")

	assert.Panics(t, func() {
		_, _ = Load()
	}, "expected panic for short encryption key")
}

func TestLoad_InvalidEncryptionKeyLength_TooLong(t *testing.T) {
	unsetTestEnvs(t)
	setRequiredEnvs(t)
	// 128 hex chars = 64 raw bytes, more than required 32
	key := ""
	for i := 0; i < 128; i++ {
		key += "a"
	}
	os.Setenv("PLATFORM_SECRET_ENCRYPTION_KEY", key)

	assert.Panics(t, func() {
		_, _ = Load()
	}, "expected panic for long encryption key")
}

func TestLoad_Raw32ByteEncryptionKey(t *testing.T) {
	unsetTestEnvs(t)
	setRequiredEnvs(t)
	// Raw 32 bytes (not hex-encoded) — validate() should accept them
	os.Setenv("PLATFORM_SECRET_ENCRYPTION_KEY", "abcdefghijklmnopqrstuvwxyz123456")

	cfg, err := Load()
	assert.NoError(t, err)
	assert.NotNil(t, cfg)
	assert.Equal(t, "abcdefghijklmnopqrstuvwxyz123456", cfg.PlatformSecretEncryptionKey)
}

func TestConfig_StructFields(t *testing.T) {
	// Compilation-level check that Config has all expected fields
	cfg := &Config{
		Port:                        "8080",
		ENV:                         "development",
		AdminAPIKey:                 "key",
		DatabaseURL:                 "db-url",
		RedisURL:                    "redis-url",
		PythonServiceURL:            "py-url",
		PythonServiceTimeout:        35,
		JWTSecret:                   "secret",
		JWTExpire:                   24,
		RateLimitGlobal:             1000,
		RateLimitUserMsg:            60,
		PlatformSecretEncryptionKey: "key-32-bytes",
		AlertWebhookURL:             "webhook",
	}
	assert.Equal(t, "8080", cfg.Port)
	assert.Equal(t, "development", cfg.ENV)
	assert.Equal(t, true, true) // struct compiles cleanly
}

func TestLoad_ProductionEnv(t *testing.T) {
	unsetTestEnvs(t)
	setRequiredEnvs(t)
	os.Setenv("ENV", "production")

	cfg, err := Load()
	assert.NoError(t, err)
	assert.NotNil(t, cfg)
	assert.Equal(t, "production", cfg.ENV)
}

func TestLoad_StagingEnv(t *testing.T) {
	unsetTestEnvs(t)
	setRequiredEnvs(t)
	os.Setenv("ENV", "staging")

	cfg, err := Load()
	assert.NoError(t, err)
	assert.NotNil(t, cfg)
	assert.Equal(t, "staging", cfg.ENV)
}

func mustParseDuration(t *testing.T, s string) time.Duration {
	t.Helper()
	d, err := time.ParseDuration(s)
	if err != nil {
		t.Fatalf("invalid duration %q in test: %v", s, err)
	}
	return d
}
