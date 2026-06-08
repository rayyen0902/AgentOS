# Step 7 消项清单

> 负责：企微 / 抖音 / 小红书 Webhook 适配器
> GitHub Issue: #12, #20(部分)

---

## 🔴 Critical — #12 (3 条)

- [x] **S7-01** `go-service/internal/platform/wecom.go:67` — `HandleVerify` echostr 解密: `[]byte(cfg.EncodingAESKey+"=")` 直接当 AES bytes，不解码 base64。改为 `base64.StdEncoding.DecodeString(key+"=")` — fixed: added `decodeAESKey()` helper that does `base64.StdEncoding.DecodeString(encodingAESKey + "=")` with 32-byte length validation
- [x] **S7-02** `go-service/internal/platform/wecom.go:118` — `HandleMessage` 消息体解密同上 bug — fixed: message body now decoded via `base64.StdEncoding.DecodeString(encMsg.Encrypt)` then AES-decrypted using key from `decodeAESKey()`
- [x] **S7-03** `go-service/internal/platform/wecom.go:327` — `aesEncrypt` 加密同上 bug — fixed: `aesEncrypt` now accepts decoded key bytes from `decodeAESKey()`, correctly performing AES-CBC encrypt with PKCS7 padding and returning base64-encoded ciphertext

---

## 🟠 High — #20(部分) (4 条)

- [x] **S7-04** `go-service/internal/platform/security.go:76` — `DefaultXHSVerifier` 硬编码返回 false 但代码继续处理。实现真实 RSA 签名验证 — fixed: `VerifyXHSRSA` now performs real RSA PKCS#1 v1.5 + SHA-256 verification with PEM public key parsing, base64 signature decoding, and `rsa.VerifyPKCS1v15()`
- [x] **S7-05** `go-service/internal/platform/douyin.go:166` — `pushTextMessage` 直接调 API URL 不带 access_token。实现 `getAccessToken()` + Redis `access_token:douyin:{app_id}` 缓存 — fixed: added `getAccessToken()` with Redis caching + `client_credential` grant flow, bearer token in `Authorization` header via `postWithRetry()`
- [x] **S7-06** `go-service/internal/platform/xhs.go:148` — `pushMessage` 同上，无 access_token。实现 token 管理 + `Authorization: Bearer <token>` 头 — fixed: added `getAccessToken()` with Redis caching + `client_credential` grant flow, `postWithRetry()` sends `Authorization: Bearer` header
- [x] **S7-07** `go-service/internal/platform/wecom.go:180` — AgentID 硬编码 `1000002`。应读 `TenantPlatform` 配置 — fixed: added `getAgentID()` method that reads `cfg.WeComAgentID`, falls back to 1000002; `GetPlatformConfig` queries `wecom_agent_id` column with `sql.NullInt64`

---

## 🟡 Medium (4 条)

- [x] **S7-08** `go-service/internal/platform/douyin.go:168` — `pushTextMessage` 重试路径 resp.Body 未关闭。第一次 POST 失败的 response body 泄漏 — fixed: `postWithRetry()` now reads and closes `resp.Body` on every path via `io.ReadAll` + `Body.Close()` on each attempt
- [x] **S7-09** `go-service/internal/platform/xhs.go` — `pushMessage` 同上 resp.Body 泄漏 — fixed: XHS `postWithRetry()` mirrors douyin pattern, reads + closes `resp.Body` on every attempt
- [x] **S7-10** `go-service/internal/platform/manager.go:190` — `incrementFailCount` 用 `json.Marshal/Unmarshal` 操作整数计数。改为 Redis `INCR` — fixed: replaced `json.Marshal/Unmarshal` round-trip with `redis.Incr()` atomic increment, with separate `Expire` call for TTL renewal
- [x] **S7-11** `go-service/internal/platform/manager.go:219` — `sendAlert` goroutine 无错误上报。告警发送失败仅本地 log — fixed: removed fire-and-forget goroutine, replaced with synchronous `http.NewRequestWithContext` + context timeout; logs detailed errors for request creation, send failure, and non-2xx responses

---

## 🟢 Low (3 条)

- [x] **S7-12** `go-service/internal/platform/douyin.go:166` — API URL hardcode `https://open.douyin.com/im/send_msg/`。改为配置读取 — fixed: reads `cfg.WebhookURL` first, falls back to hardcoded default only when empty
- [x] **S7-13** `go-service/internal/platform/xhs.go:148` — API URL hardcode。同上改为配置读取 — fixed: reads `cfg.WebhookURL` first, falls back to hardcoded default only when empty
- [x] **S7-14** `go-service/internal/platform/wecom.go:247` — token 过期重试时 `context.Background()` 无超时。改为 `context.WithTimeout` — fixed: `getAccessToken()` uses `context.WithTimeout(5s)`, `sendActivePush` token-refresh path uses `context.WithTimeout(3s)` for Redis delete, both with proper `cancel()`
