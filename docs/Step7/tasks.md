# Step 7 消项清单

> 你负责：企微 / 抖音 / 小红书 Webhook 适配器

---

## #12 【Critical】企微 AES Key 未 base64 解码，Webhook 解密全乱码

**文件**: `go-service/internal/platform/wecom.go`

**位置**:
- `HandleVerify` 行 67: echostr 解密
- `HandleMessage` 行 118: 消息体解密
- `aesEncrypt` 行 327: 加密

**问题**: `EncodingAESKey` 是 43 字符 base64，代码 `[]byte(key+"=")` 直接当 AES bytes。base64 字符串字节 ≠ base64 解码后的密钥。

**修复**: 
```go
keyBytes, err := base64.StdEncoding.DecodeString(cfg.EncodingAESKey + "=")
if err != nil { return err }
block, err := aes.NewCipher(keyBytes)  // ← 用解码后的 32 bytes
```

---

## #20 部分归属 Step 7【High】抖音/小红书主动推送无 access_token

**文件**: 
- `go-service/internal/platform/douyin.go`
- `go-service/internal/platform/xhs.go`

**修复**:
1. **抖音**: 实现 `getAccessToken()` → 从 Redis `access_token:douyin:{app_id}` 读，过期自动刷新
2. **小红书**: 同上，实现 token 管理
3. 主动推送 API 调用加 `Authorization: Bearer <token>` 头
4. 抖音 API URL 从 hardcode 改为配置读

---

## 关联：低优先级

- `douyin.go` `pushTextMessage` 重试路径 resp.Body 未关闭——加 defer close
- `xhs.go` `pushMessage` 同上
- `wecom.go` 写死 `AgentID: 1000002` → 读 `TenantPlatform` 配置
- `security.go:76` 小红书签名验证硬编码返回 false → 实现真实 RSA 签名验证
- `manager.go` `incrementFailCount` 用 JSON Marshal/Unmarshal 计数 → 改用 Redis INCR
- `manager.go` `sendAlert` goroutine 无错误上报——加告警日志
