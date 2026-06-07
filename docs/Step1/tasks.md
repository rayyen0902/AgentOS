# Step 1 消项清单

> 你负责：DB Migration + Redis + 环境变量

---

## #24 【High】DB Migration: 索引未用 CONCURRENTLY + ttl_seconds 缺失 + 单文件

**文件**: `migrations/001_step1_infrastructure.sql`

**修复项**:
1. `idx_products_embedding` 需改为 `CREATE INDEX CONCURRENTLY`（生产锁表风险），或拆为独立非事务脚本
2. `session_states` 表补充 `ttl_seconds INT DEFAULT 1800` 列（PRD 4.1.1 规定）
3. `knowledge.product_conflicts` 的 `SERIAL` 改为 `BIGSERIAL`，与其他表一致
4. `tenant_platforms` 补充 `updated_at TIMESTAMPTZ DEFAULT NOW()` 列

**PRD 参照**: 第 13 节，4.1.1 节

---

## 关联：低优先级改进

- `config.go` 补充 `PlatformSecretEncryptionKey` 的 32-byte 长度校验（AES-256 要求，否则 panic）
- `config.go` 的 `getIntEnv`/`getDurationEnv` 解析失败时加 warning 日志
