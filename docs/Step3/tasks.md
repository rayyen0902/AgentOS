# Step 3 消项清单

> 负责：Go 路由 + 中间件 + SSE Handler + SessionState + Go→Python 转发
> GitHub Issue: #2, #3, #20, #26

---

## 🔴 Critical — #2, #3 (2 条)

- [x] **S3-01** `go-service/internal/sse/broker.go` — SSE Broker 竞态。`Publish` 读锁迭代时 `Unsubscribe` 写锁关闭 channel，已捕获 channel 被关闭后 `ch <- evt` → panic。用 `recover + select + default` 保护发送 **→ `Publish` 内嵌 recover 闭包**
- [x] **S3-02** `go-service/internal/handler/forward.go` — `forwardNormalized()` 只返回 reply 文本。Python 响应的 card/interrupt/status 事件全丢弃，未写入 SSE Broker 或 Redis Stream。返回完整 events 数组并逐条写入 **→ `forwardNormalized` 提取 events 逐条 `SSEBroker.Publish`**

---

## 🟠 High — #20 (1 条)

- [x] **S3-03** `go-service/internal/handler/handler.go` — SSE 端点 `GET /api/v1/chat/stream` 在 auth 白名单外。浏览器 `EventSource` 不支持 `Authorization` header → SSE 必 401。支持 query param token: `?session_id=xxx&token=yyy` **→ auth.Middleware 提取 query token 并 fallback**

---

## 🟡 Medium — #26 (6 条)

- [x] **S3-04** `go-service/internal/model/session.go` — `StatusEvent` 缺少 PRD 4.1.1 规定的 `duration_ms` 和 `created_at` 字段 **→ 已添加**
- [x] **S3-05** `go-service/internal/session/manager.go` — `Set()` 中 `TTLSeconds` 存了但永远用 `30*time.Minute` 硬编码。应读 `state.TTLSeconds` **→ 读 state.TTLSeconds 动态 TTL**
- [x] **S3-06** `go-service/internal/session/manager.go` — `PublishSSE` 的 `XAdd` 写 Redis Stream 后无 `EXPIRE`。PRD 4.3.1 规定 `sse_channel:{id}` TTL 3600s **→ XAdd 后 Expire 3600s**
- [x] **S3-07** `go-service/internal/platform/normalize.go` — `openIDToUserID` 哈希不加 tenant_id，不同租户相同 openID → 同一 UserID，跨租户碰撞 **→ 签名加 tenantID 参数**
- [x] **S3-08** `go-service/internal/middleware/middleware.go` — 内存限流器 `userBucket` map 无界增长，从不驱逐旧条目 **→ 添加 evictLoop 定期驱逐**
- [x] **S3-09** `go-service/internal/middleware/middleware.go` — `WriteJSON` 中 `httpStatus` 先后赋值两次（行 111-116），冗余 if/else **→ 简化为单行调用 model.HTTPStatus**

---

## 🟢 Low (6 条)

- [x] **S3-10** `go-service/cmd/server/main.go:86-96` — 中间件编号 (5,4,3,2,1) 与包裹顺序矛盾，注释写 "outermost" vs "innermost" 冲突 **→ 统一注释说明包裹顺序**
- [x] **S3-11** `go-service/internal/middleware/middleware.go:56` — Logger 用 `log.Printf` 手拼 JSON 字符串，非结构化输出。改用 `encoding/json` 或 `slog` **→ 改用 slog.NewJSONHandler**
- [x] **S3-12** `go-service/internal/middleware/middleware.go` — `newUUID()` 忽略 `crypto/rand.Read` 的 error 返回值 **→ 检查 error 并 fallback**
- [x] **S3-13** `go-service/cmd/server/main.go` — shutdown 时 SSE Broker 的 subscriber channels 未 drain/close，goroutine 泄漏 **→ unsubscribe 一键 drain+close**
- [x] **S3-14** `go-service/internal/handler/forward.go` — 4 个 forward 函数 (`forwardToPython`/`V2`/`Normalized`/`Resume`) 97% 重复 **→ 提取 `pythonRequest` 统一实现，4 个函数全部代理**
- [x] **S3-15** `go-service/internal/handler/forward.go:274` — `serializeAgentState` 静默丢弃 `json.Unmarshal` 错误 **→ 检查 Unmarshal error 并 WARN 日志**
- [x] **S3-16** `go-service/internal/handler/handler.go` — Auth 桩函数 (Register/Login/SendCode/approve) 全部返回 hardcode 占位数据 **→ 添加 `TODO(Step 4)` 注释标注；所有 stub 返回有效 JSON 占位数据**。fixes #26
- [x] **S3-17** `go-service/internal/handler/handler.go:198` — `handleResume` 传 `nil` 给 `forwardResumeToPython`，trace chain 断裂 **→ 早已修复（commit 4340324）：`ctx := r.Context()` 逐层传递至 `forwardResumeToPython`**。fixes #26
