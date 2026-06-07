# Step 3 消项清单

> 你负责：Go 路由 + 中间件 + SSE Handler + SessionState + Go→Python 转发

---

## #2 【Critical】SSE Broker 竞态: Publish 与 Unsubscribe 并发

**文件**: `go-service/internal/sse/broker.go`

**问题**: `Publish` 读锁迭代订阅者时，`Unsubscribe` 写锁关闭 channel。已捕获的 channel 被关闭后 `ch <- evt` → panic。

**修复**: 发送用 `select + default` 或 `Unsubscribe` 改为惰性关闭（标记删除，由 GC 回收）。

---

## #3 【Critical】平台异步路径丢弃全部 SSE 事件

**文件**: `go-service/internal/handler/forward.go`

**问题**: `forwardNormalized()` 只返回 reply 文本。Python 响应的 card/interrupt/status 事件全丢弃，未写入 SSE Broker 或 Redis Stream。

**修复**: 
1. `forwardNormalized` 返回完整 Python 响应（含 events 数组）
2. 将 events 逐条写入 `sse_channel:{session_id}` Redis Stream
3. 非 Web Demo 渠道通过 platform manager 的主动推送通道投递

---

## #20 【High】SSE 端点认证冲突

**文件**: `go-service/internal/handler/handler.go`

**问题**: 浏览器 `EventSource` 不能带 `Authorization` header，但 `GET /api/v1/chat/stream` 在 auth 白名单外 → SSE 连接必 401。

**修复**: SSE 端点支持 query param token 认证：`/api/v1/chat/stream?session_id=xxx&token=yyy`，在 auth 中间件中额外检查 query param。

---

## #26 【Medium】Go: TTLSeconds + StatusEvent + Stream TTL + openID + 限流器

**文件**: 多个

| 文件 | 问题 | 修复 |
|------|------|------|
| `model/session.go` | `TTLSeconds` 存了但 `Set()` 永远 30min | `Set()` 读 `state.TTLSeconds` |
| `model/session.go` | `StatusEvent` 缺 `duration_ms` / `created_at` | 补字段 |
| `session/manager.go` | Redis Stream `XAdd` 后无 TTL | 加 `EXPIRE` |
| `platform/normalize.go` | `openIDToUserID` 跨租户碰撞 | 哈希加 tenant_id |
| `middleware/middleware.go` | userBucket map 无界增长 | 加 TTL 驱逐 |
| `middleware/middleware.go` | `WriteJSON` 冗余赋值 | 精简 if/else |

---

## 关联：低优先级

- `cmd/server/main.go` 中间件编号与包裹顺序矛盾——统一注释
- `middleware.go` Logger 用 `log.Printf` 拼 JSON——改用 `encoding/json`
- `newUUID()` 忽略 `rand.Read` 错误
