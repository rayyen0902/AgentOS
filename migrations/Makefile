# AgentOS Migration Makefile
# 迁移工具: golang-migrate v4
# 安装: go install -tags 'postgres' github.com/golang-migrate/migrate/v4/cmd/migrate@latest

DATABASE_URL ?= postgres://agentos:agentos123@localhost:5432/agentos?sslmode=disable
MIGRATIONS_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))

.PHONY: up down version create force

# 执行所有待执行的迁移
up:
	migrate -path "$(MIGRATIONS_DIR)" -database "$(DATABASE_URL)" up

# 回滚最近一次迁移
down:
	migrate -path "$(MIGRATIONS_DIR)" -database "$(DATABASE_URL)" down 1

# 回滚所有迁移
down-all:
	migrate -path "$(MIGRATIONS_DIR)" -database "$(DATABASE_URL)" down -all

# 查看当前版本和脏状态
version:
	migrate -path "$(MIGRATIONS_DIR)" -database "$(DATABASE_URL)" version

# 强制执行版本（跳过脏状态校验，慎用）
force:
	@read -p "Enter version to force: " V; \
	migrate -path "$(MIGRATIONS_DIR)" -database "$(DATABASE_URL)" force $$V

# 创建新迁移文件
# 用法: make create NAME=add_xxx_table
create:
	migrate create -ext sql -dir "$(MIGRATIONS_DIR)" -seq $(NAME)
