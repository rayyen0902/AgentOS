# Step 7：平台适配器

> **上下文范围**：PRD 第 10 节（消息投递通道）、第 12 节（平台渠道接入）、第 12.1（Webhook 安全规范）
> **前置依赖**：Step 3（Go 骨架 + Webhook 路由）、Step 6A（前台 Agent 可用）
> **完成标准**：企微/抖音/小红书 Webhook 验签通过，消息收发正常，主动推送可用

---

## 7.1 各渠道投递方式

| 渠道 | 被动回复（同步） | 主动推送（异步） | 中断反调 |
|------|-----------------|-----------------|----------|
| 企微 | Webhook 200 响应 XML | POST `/cgi-bin/message/send` | 主动推送文本+按钮卡片 |
| 抖音 | Webhook 200 响应 | POST `/im/send_msg/` | 主动推送文本+选项 |
| 小红书 | Webhook 200 响应 | 私信 API | 主动推送文本+选项 |
| Web Demo | HTTP 200 | SSE / 轮询(降级) | SSE push InterruptCard |

---

## 7.2 Webhook 安全规范

| 渠道 | 验签方式 | Go 实现要点 |
|------|---------|------------|
| 企微 | SHA1(token + timestamp + nonce + echostr) | 使用 `wxbizmsgcrypt` 库 |
| 抖音 | HMAC-SHA256(app_secret + timestamp + nonce + body) | 标准 HMAC |
| 小红书 | RSA 签名（官方 SDK） | 按官方文档实现 |

所有 Webhook 验签失败 → 返回 403，记录 `tenant_id` + IP 到 security_log，连续 10 次失败 → 触发告警。

---

## 7A：企微适配器

### 接入流程

1. 品牌方在企微管理后台配置回调 URL：`https://api.hufu.cn/api/v1/webhook/wecom/{tenant_id}`
2. 企微发送 `GET` 请求验证 URL（含 `msg_signature`、`timestamp`、`nonce`、`echostr` 参数）
3. Go 层解密 `echostr` 并返回明文
4. 验证通过后，企微开始 `POST` 消息到该 URL

### 消息模型

```
用户发消息 → 企微服务器 POST 到 Webhook
  → Go 验签 + AES 解密
  → 归一化为内部消息格式
  → 转发 Python /agent/run
  → Go 被动回复 200 OK（XML 格式）"收到，正在处理..."
  → 异步 goroutine 等待子 Agent 结果
  → 主动调用 POST /cgi-bin/message/send 推送结果卡片
```

### 消息时序

```
T+0ms     企微服务器 POST 用户消息到 Webhook
T+200ms   Go 验签 → 归一化 → 转发 Python
T+400ms   前台 Agent 回复 → Go 被动回复 200 OK
T+800ms   子 Agent 启动（后台 goroutine）
T+1.2s    子 Agent: FE 检索完成
T+3.0s    子 Agent: 产品匹配完成
T+3.1s    Go 主动调用企微 API 推送结果卡片
```

### 配置存储

- `tenant_platforms` 表：`app_id`（CorpID）、`app_secret_encrypted`（AES-256-GCM 加密）、`token`、`encoding_aes_key`
- AccessToken 缓存：`access_token:wecom:{corp_id}` Redis Key，TTL = expires_in - 60s
- AccessToken 过期 → 自动刷新，失败则主动推送进入队列重试（最多 3 次）

### 消息格式

**接收**：XML（加密）
**被动回复**：XML（加密）
**主动推送**：JSON → `POST /cgi-bin/message/send`

---

## 7B：抖音适配器

### 接入流程

1. 品牌方在抖音开放平台配置消息推送 URL
2. 抖音发送 `GET` 请求验证（HMAC-SHA256 签名）
3. Go 层返回 `echostr`
4. 验证通过后接收 `POST` 消息

### 消息模型

```
用户发消息 → 抖音服务器 POST 到 Webhook
  → Go HMAC-SHA256 验签
  → 归一化
  → 转发 Python /agent/run
  → Go 被动回复 200 OK
  → 异步 goroutine
  → 主动调用 POST /im/send_msg/ 推送
```

### 中断反调

- 抖音不支持卡片，中断确认用文本 + 数字选项："请回复：1.没有过敏 2.烟酰胺过敏 3.水杨酸过敏"

---

## 7C：小红书适配器

### 接入流程

1. 品牌方在小红书开放平台配置回调 URL
2. RSA 签名验证（使用官方 SDK）
3. 消息接收 + 被动回复 + 主动推送

### 消息模型

与企微类似，私信 API 主动推送。

---

## 7.4 消息归一化

所有平台消息统一转换为内部格式：

```json
{
  "session_id": "conv_abc123",
  "user_id": 42,
  "tenant_id": 1,
  "platform": "wecom",
  "message": {
    "type": "text",
    "content": "我是油皮，推荐个洗面奶",
    "image_url": null
  },
  "agent_state": {}
}
```

platform 字段：`web` | `wecom` | `douyin` | `xhs`

---

## 7.5 平台配置数据库表

```sql
-- tenant_platforms（Step 1 已创建）
-- 字段：tenant_id, platform, app_id, app_secret_hash, app_secret_encrypted,
--       token, encoding_aes_key, webhook_url, status
```

- `app_secret_hash`：SHA-256，用于验签
- `app_secret_encrypted`：AES-256-GCM 加密存储，用于主动推送 API 调用
- 加密密钥来自 `PLATFORM_SECRET_ENCRYPTION_KEY` 环境变量

---

## 7.6 验收标准

### 企微

- [ ] URL 验证（GET echostr）解密正确
- [ ] 消息接收（POST）验签 + AES 解密成功
- [ ] 被动回复 XML 格式正确
- [ ] 主动推送 `POST /cgi-bin/message/send` 成功
- [ ] AccessToken 自动刷新机制正常
- [ ] AccessToken 过期重试（最多 3 次）生效

### 抖音

- [ ] URL 验证 HMAC-SHA256 签名通过
- [ ] 消息接收 + 归一化正常
- [ ] 主动推送 `POST /im/send_msg/` 成功
- [ ] 中断反调用数字选项替代卡片

### 小红书

- [ ] RSA 签名验证通过
- [ ] 消息接收正常
- [ ] 私信 API 主动推送可用

### 通用

- [ ] 验签失败 → 403 + security_log 记录
- [ ] 连续 10 次验签失败 → 告警触发
- [ ] 所有平台消息归一化格式一致
- [ ] `tenant_platforms` 配置 CRUD 可用
