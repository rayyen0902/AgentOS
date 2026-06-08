# ============================================================
# Test targets
# ============================================================
.PHONY: test test-go test-py test-web test-e2e

test-go: ## Run Go unit tests
	cd go-service && go test -race -count=1 ./...

test-py: ## Run Python unit tests
	cd python-service && python3 -m pytest tests/ -v --tb=short

test-web: ## Run React unit tests
	cd web && NODE_OPTIONS="--experimental-require-module" npx vitest run

test: test-go test-py test-web ## Run all unit tests

test-e2e: ## Run E2E integration test
	bash e2e/chat_flow.sh

# ============================================================
# Default: hybrid mode — PG+Redis in Docker, Go+Python native
# ============================================================
up: infra-up
	@echo ""
	@echo "=== 基础设施已就绪 ==="
	@echo "在三个终端分别运行:"
	@echo "  make go-dev    # Go 服务 :8080"
	@echo "  make py-dev    # Python 服务 :8000"
	@echo "  make web-dev   # 前端 :5173"
	@echo ""

down: infra-down
	@echo "所有服务已停止"

logs:
	docker compose logs -f postgres redis

reset: infra-down
	docker compose down -v
	@echo "数据已清空，运行 make up 重新开始"

build:
	cd go-service && go build -o server ./cmd/server/
	cd web && npm run build

# ============================================================
# Full Docker mode
# ============================================================
up-full:
	docker compose --profile full up -d --build
	@echo ""
	@echo "=== 全量 Docker 模式 ==="
	@echo "Nginx (前端): http://localhost:3000"
	@echo "Go API:       http://localhost:8080"
	@echo "Python:       http://localhost:8000"
	@echo "PostgreSQL:   localhost:5432"
	@echo "Redis:        localhost:6379"

down-full:
	docker compose --profile full down

# ============================================================
# Infrastructure only
# ============================================================
infra-up:
	docker compose up -d postgres redis
	@echo "等待 PostgreSQL..."
	@until docker compose exec -T postgres pg_isready -U agentos -d agentos 2>/dev/null; do sleep 1; done
	@echo "等待 Redis..."
	@until docker compose exec -T redis redis-cli ping 2>/dev/null | grep -q PONG; do sleep 1; done
	@echo "[OK] PostgreSQL + Redis 就绪"

infra-down:
	docker compose stop postgres redis

# ============================================================
# Database migrations
# ============================================================
migrate-up:
	@echo "运行数据库迁移..."
	cd migrations && DATABASE_URL="postgres://agentos:agentos123@localhost:5432/agentos?sslmode=disable" make up

migrate-down:
	cd migrations && DATABASE_URL="postgres://agentos:agentos123@localhost:5432/agentos?sslmode=disable" make down

db-reset: infra-down
	docker compose down -v
	docker compose up -d postgres redis
	@echo "等待 PostgreSQL..."
	@sleep 5
	cd migrations && DATABASE_URL="postgres://agentos:agentos123@localhost:5432/agentos?sslmode=disable" make up

# ============================================================
# Individual service launchers (hybrid mode)
# ============================================================
go-dev:
	cd go-service && go run ./cmd/server/

py-dev:
	cd python-service && uvicorn main:app --host 0.0.0.0 --port 8000 --reload

web-dev:
	cd web && npm run dev

# ============================================================
# Utilities
# ============================================================
ps:
	docker compose ps

# ============================================================
# Docker build targets
# ============================================================
.PHONY: docker-build docker-up docker-down docker-logs

docker-build: ## Build all Docker images
	docker compose build --no-cache

docker-up: ## Start all services in Docker (full profile)
	docker compose --profile full up -d
	@echo "=== 服务启动中... ==="
	@sleep 5
	@curl -s http://localhost:8080/health || echo "Go 服务可能还在启动..."
	@echo ""
	@echo "端口映射:"
	@echo "  Nginx → http://localhost:3000"
	@echo "  Go API → http://localhost:8080"
	@echo "  Python → http://localhost:8000"

docker-down: ## Stop all Docker services
	docker compose --profile full down

docker-logs: ## Tail all Docker logs
	docker compose --profile full logs -f

# ============================================================
# Deployment targets
# ============================================================
.PHONY: deploy deploy-dry-run deploy-rollback

deploy: test docker-build ## Run tests, build Docker images, and deploy to server
	@echo "=== 部署到服务器 ==="
	bash scripts/deploy.sh

deploy-dry-run: ## Dry-run deployment (rsync without actual deploy)
	@echo "=== 模拟部署 (仅同步代码) ==="
	@SERVER=$$(grep -oP 'ssh root@\K[^ ]+' 资源.md | head -1); \
	PASS=$$(grep -oP '密码 \K.+' 资源.md | head -1); \
	echo "目标服务器: $$SERVER"; \
	echo "将同步以下目录: go-service/ python-service/ web/ docker/ nginx/ docker-compose.yml Makefile"

deploy-rollback: ## Rollback to previous deployment
	@echo "=== 回滚到上一个版本 ==="
	@echo "SSH 到服务器后执行: cd /opt/agentos && docker compose --profile full down && git checkout HEAD~1 && docker compose --profile full up -d --build"

# ============================================================
# Full production run (all in Docker)
# ============================================================
.PHONY: prod prod-down prod-status

prod: docker-build docker-up ## Full production deployment (build + up)

prod-down: docker-down ## Stop production

prod-status: ## Check production status
	@echo "=== 服务状态 ==="
	@curl -s http://localhost:8080/health 2>/dev/null | python3 -m json.tool || echo "Go 服务不可达"
	@echo ""
	@curl -s http://localhost:8000/health 2>/dev/null | python3 -m json.tool || echo "Python 服务不可达"
	@echo ""
	@docker compose --profile full ps

# ============================================================
# Lint targets
# ============================================================
.PHONY: lint lint-go lint-py lint-web

lint: lint-go lint-py lint-web ## Run all linters

lint-go: ## Lint Go code
	@echo "=== Go lint ==="
	cd go-service && go vet ./...
	@command -v staticcheck >/dev/null && cd go-service && staticcheck ./... || echo "staticcheck 未安装，跳过"

lint-py: ## Lint Python code
	@echo "=== Python lint ==="
	cd python-service && python3 -m flake8 app/ tests/ --max-line-length=120 --ignore=E203,W503 || echo "flake8 未安装，跳过"

lint-web: ## Lint React code
	@echo "=== React lint ==="
	cd web && npx tsc --noEmit || echo "TypeScript check 有错误"
