package db

import (
	"database/sql"
	"fmt"

	_ "github.com/lib/pq"
)

func New(databaseURL string) (*sql.DB, error) {
	db, err := sql.Open("postgres", databaseURL)
	if err != nil {
		return nil, fmt.Errorf("sql.Open: %w", err)
	}

	db.SetMaxOpenConns(25)
	db.SetMaxIdleConns(10)

	if err := db.Ping(); err != nil {
		return nil, fmt.Errorf("db.Ping: %w", err)
	}

	// Verify pgvector extension is available
	var hasVector bool
	err = db.QueryRow("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='vector')").Scan(&hasVector)
	if err != nil {
		return nil, fmt.Errorf("pgvector check: %w", err)
	}
	if !hasVector {
		// pgvector not installed — non-fatal in dev mode, app will start without vector support
		// Vector-dependent features (product embeddings) will be unavailable
		fmt.Println("[WARN] pgvector extension is not enabled — vector search features disabled")
	}

	return db, nil
}
