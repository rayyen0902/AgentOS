# Step 7 消项清单

> 负责：企微 / 抖音 / 小红书 Webhook 适配器
> GitHub Issue: #12, #20(部分)

---

## 🔴 Critical — #12 (3 条)

- [ ] **S7-01** `go-service/internal/platform/wecom.go:67` — `HandleVerify` echostr 解密: `[]byte(cfg.EncodingAESKey+"=")` 直接当 AES bytes，不解码 base64。改为 `base64.StdEncoding.DecodeString(key+"=")`
- [ ] **S7-02** `go-service/internal/platform/wecom.go:118` — `HandleMessage` 消息体解密同上 bug
- [ ] **S7-03** `go-service/internal/platform/wecom.go:327` — `aesEncrypt` 加密同上 bug

---

## 🟠 High — #20(部分) (4 条)

- [ ] **S7-04** `go-service/internal/platform/security.go:76` — `DefaultXHSVerifier` 硬编码返回 false 但代码继续处理。实现真实 RSA 签名验证
- [ ] **S7-05** `go-service/internal/platform/douyin.go:166` — `pushTextMessage` 直接调 API URL 不带 access_token。实现 `getAccessToken()` + Redis `access_token:douyin:{app_id}` 缓存
- [ ] **S7-06** `go-service/internal/platform/xhs.go:148` — `pushMessage` 同上，无 access_token。实现 token 管理 + `Authorization: Bearer <token>` 头
- [ ] **S7-07** `go-service/internal/platform/wecom.go:180` — AgentID 硬编码 `1000002`。应读 `TenantPlatform` 配置

---

## 🟡 Medium (4 条)

- [ ] **S7-08** `go-service/internal/platform/douyin.go:168` — `pushTextMessage` 重试路径 resp.Body 未关闭。第一次 POST 失败的 response body 泄漏
- [ ] **S7-09** `go-service/internal/platform/xhs.go` — `pushMessage` 同上 resp.Body 泄漏
- [ ] **S7-10** `go-service/internal/platform/manager.go:190` — `incrementFailCount` 用 `json.Marshal/Unmarshal` 操作整数计数。改为 Redis `INCR`
- [ ] **S7-11** `go-service/internal/platform/manager.go:219` — `sendAlert` goroutine 无错误上报。告警发送失败仅本地 log

---

## 🟢 Low (3 条)

- [ ] **S7-12** `go-service/internal/platform/douyin.go:166` — API URL hardcode `https://open.douyin.com/im/send_msg/`。改为配置读取
- [ ] **S7-13** `go-service/internal/platform/xhs.go:148` — API URL hardcode。同上改为配置读取
- [ ] **S7-14** `go-service/internal/platform/wecom.go:247` — token 过期重试时 `context.Background()` 无超时。改为 `context.WithTimeout`
