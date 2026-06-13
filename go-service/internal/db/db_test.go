package db

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestNew_MissingDatabaseURL(t *testing.T) {
	// sql.Open with empty DSN does not error immediately, but Ping will fail.
	_, err := New("")
	assert.Error(t, err)
}

func TestNew_InvalidDatabaseURL(t *testing.T) {
	_, err := New("invalid-dsn-formatly-missing-parts")
	assert.Error(t, err)
}

func TestNew_ConnectionRefused(t *testing.T) {
	// Use a valid-looking postgres URL pointing to a port that is unlikely open.
	// The test expects a connection/Ping error, not a config parsing error.
	_, err := New("postgres://localhost:54321/testdb?sslmode=disable")
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "db.Ping")
}
