# Step 1 消项清单

> 负责：DB Migration + Redis + 环境变量
> GitHub Issue: #24

---

## 🔴 Critical — 0 条

---

## 🟠 High — #24 (1 条)

- [x] **S1-01** ~~`migrations/001_step1_infrastructure.sql`~~ — `idx_products_embedding` 未用 `CONCURRENTLY` → **已修复**：拆为独立 `010_idx_products_embedding.up.sql`，使用 `CREATE INDEX CONCURRENTLY IF NOT EXISTS`，通过 golang-migrate `disableTransaction: true` 执行。fixes #24

---

## 🟡 Medium (3 条)

- [x] **S1-02** ~~`migrations/001_step1_infrastructure.sql`~~ — `session_states` 缺 `ttl_seconds` 列 → **已修复**：`005_create_session_states.up.sql` 新增 `ttl_seconds INT DEFAULT 1800`
- [x] **S1-03** ~~`migrations/001_step1_infrastructure.sql`~~ — 单文件 vs 10 步分步执行 → **已修复**：拆为 001_alter_tenants 到 010_idx_products_embedding 共 10 对 up/down 文件，按依赖顺序编号
- [x] **S1-04** ~~`migrations/001_step1_infrastructure.sql`~~ — 未指定迁移工具 → **已修复**：统一使用 `golang-migrate v4`，附带 `migrations/Makefile`（含 up/down/version/create/force 命令）

---

## 🟢 Low (3 条)

- [x] **S1-05** ~~`migrations/001_step1_infrastructure.sql`~~ — `knowledge.product_conflicts` 用 `SERIAL` 而非 `BIGSERIAL` → **已修复**：`009_create_knowledge_product_conflicts.up.sql` 改为 `BIGSERIAL`
- [x] **S1-06** ~~`migrations/001_step1_infrastructure.sql`~~ — `tenant_platforms` 缺 `updated_at` → **已修复**：`004_create_tenant_platforms.up.sql` 新增 `updated_at TIMESTAMPTZ DEFAULT NOW()`
- [x] **S1-07** ~~`migrations/001_step1_infrastructure.sql`~~ — `session_states` 的 `user_id`/`tenant_id` 无外键 → **已确认**：PRD 设计初衷避免跨库外键复杂化，`005_create_session_states.up.sql` 已添加注释说明

---

## ⚪ 关联：config.go 低优先级 (2 条)

- [x] **S1-08** ~~`go-service/internal/config/config.go`~~ — `PlatformSecretEncryptionKey` 缺少 32-byte 长度校验 → **已修复**：`validate()` 中新增 AES-256 32-byte key 长度校验，不满足直接 `panic`（支持 hex 编码 64-char 或 raw 32-byte）
- [x] **S1-09** ~~`go-service/internal/config/config.go`~~ — `getIntEnv`/`getDurationEnv` 静默吞错误 → **已修复**：解析失败时 `log.Printf("[WARN] config: ...")` 输出警告
