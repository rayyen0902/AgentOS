# Step 9：前端卡片 + 管理后台

> **上下文范围**：PRD 第 5.4.2（各 Agent 卡片数据规范）、第 11 节（租户自助注册）、第 16 节（前端重构）
> **前置依赖**：Step 4（React 骨架 + Zustand Store）、Step 6（各 Agent 输出格式）、Step 7（平台适配器）
> **完成标准**：4 种卡片组件渲染正常，租户注册审批流可用，PWA 安装可用

---

## 9A：卡片组件

### 9A.1 workshop_card（配药师推荐）

```json
{
  "products": [
    {
      "id": 123,
      "name": "产品名",
      "brand": "品牌",
      "category": "洗面奶",
      "price": 199,
      "reason": "适合油皮，控油不紧绷",
      "key_ingredients": ["水杨酸", "烟酰胺"],
      "image_url": "https://..."
    }
  ],
  "conflicts": [],
  "routine_tip": "早晚均可使用，避免与高浓度VC同步"
}
```

**UI 要求**：
- 产品卡片列表（图片 + 名称 + 品牌 + 价格 + 推荐理由）
- 关键成分标签（chip/badge）
- 冲突警告（如有冲突高亮红色）
- 护肤小贴士（底部文本）
- 产品点击跳转详情/购买链接

### 9A.2 skin_report_card（肤质报告）

```json
{
  "skin_type": "混合偏油",
  "dimensions": {
    "oil_level": 4,
    "sensitivity": 2,
    "hydration": 3,
    "pigmentation": 2
  },
  "concerns": ["毛孔粗大", "T区出油"],
  "recommendations": ["控油洁面", "轻薄保湿"],
  "generated_at": "2026-06-07T10:00:00Z"
}
```

**UI 要求**：
- 肤质类型大字展示
- 雷达图/柱状图展示 4 个维度（1-5 分）
- 肌肤问题列表（concerns）
- 护理建议列表（recommendations）
- 生成时间

### 9A.3 interrupt_card（中断确认）

```json
{
  "question": "您对以下成分是否有过敏史？",
  "options": ["没有过敏", "烟酰胺过敏", "水杨酸过敏"],
  "timeout_s": 300
}
```

**UI 要求**：
- 问题文本居中展示
- 选项按钮（竖向排列），点击后 POST `/api/v1/chat/message`（`interrupt_reply: true`）
- 倒计时显示（timeout_s 秒），超时自动选 options[0]
- 超时视为用户未回复 → 使用默认选项

### 9A.4 schedule_card（日报官日程）

**UI 要求**：
- 早晚时间段
- 产品 + 步骤列表
- 注意事项

---

## 9B：租户注册审批流

### 注册流程

```
品牌方访问注册页
  → 填写品牌名 + 联系人 + 手机号 + 邮箱 + 密码
  → 发送验证码（POST /api/v1/auth/send-code）
  → 提交注册（POST /api/v1/auth/register）
  → 等待审批（status: pending）
  → 管理员审批（PUT /api/v1/admin/tenants/{id}/approve）
  → 生成 API Key + widget 嵌入代码
  → 品牌方收到通知
```

### 验证码规则

- 验证码：6 位纯数字
- 有效期：10 分钟
- 同一号码频率限制：1 次 / 60 秒，5 次 / 1 小时（Go 层 Redis 限流）
- 验证码使用后立即标记 `used=true`
- 注册后 24 小时内未审批 → 自动发邮件提醒管理员

### API Key 规范

- 格式：`mimi_live_{base62(32bytes)}`（测试环境：`mimi_test_...`）
- 生成时机：管理员审批通过时自动生成
- 存储：SHA-256 哈希后存库，明文只在生成时返回一次
- 权限：API Key 绑定 tenant_id，所有请求校验归属

### 审批通过响应

```json
{
  "code": 0,
  "data": {
    "tenant_id": 42,
    "status": "active",
    "api_key": "mimi_live_xxxxxxxxxx",
    "widget_snippet": "<script src='https://hufu.cn/widget.js' data-tenant-id='42'></script>"
  }
}
```

---

## 9C：B 端管理后台

### 功能列表

| 功能 | 路由 | 说明 |
|------|------|------|
| 租户管理 | `/admin/tenants` | 列表 + 审批 + 详情 |
| Agent 评价看板 | `/admin/dashboard` | 四维指标（Accuracy / Conversion / Retention / Trust） |
| 会话日志 | `/admin/sessions` | 按租户、时间筛选 |
| 平台配置 | `/admin/platforms` | 企微/抖音/小红书接入配置 |
| 知识管理 | `/admin/knowledge` | 产品录入 + 成分管理 + 冲突规则 |

### Agent 评价看板四维指标

| 维度 | 定义 | 展示形式 |
|------|------|----------|
| Accuracy | 推荐产品是否匹配肤质 | 百分比 + 趋势图 |
| Conversion | 推荐→选购/下单转化 | 百分比 + 转化漏斗 |
| Retention | 用户 7 日内回访率 | 百分比 + 留存曲线 |
| Trust | 采纳率 / 追问率 | 百分比 + 对比图 |

---

## 9D：PWA

- Service Worker 缓存静态资源
- `manifest.json` 配置
- 离线可用（缓存消息历史）
- 添加到主屏幕

---

## 9E：widget.js 嵌入

- 品牌方可嵌入的 `<script>` 标签
- iframe + postMessage 通信
- `data-tenant-id` 属性绑定租户

---

## 9F：环境变量

```env
VITE_API_BASE_URL=https://api.hufu.cn
VITE_SSE_RECONNECT_MAX=10
VITE_ENV=production
```

---

## 9G：数据边界

| 字段 | 最大值 | 超出处理 |
|------|--------|----------|
| 消息内容 | 2000 字 | 截断并提示"消息过长，已截断至2000字" |
| 图片大小 | 10MB | 拒绝并提示重新上传 |
| SSE 单事件 | 64KB | 大卡片分块推送 |

---

## 9H：验收标准

### 卡片组件

- [ ] `workshop_card`：产品列表 + 成分标签 + 冲突警告 + 小贴士，渲染正确
- [ ] `skin_report_card`：肤质类型 + 雷达图 + concerns + recommendations
- [ ] `interrupt_card`：问题 + 选项按钮 + 倒计时 + 超时自动选择
- [ ] `schedule_card`：早晚日程渲染

### 注册审批

- [ ] 注册表单含验证码，提交流程正常
- [ ] 验证码有效期 10 分钟
- [ ] 同一手机号限流 1次/60s
- [ ] 审批页面可用，通过后生成 API Key
- [ ] API Key 仅首次返回明文

### 管理后台

- [ ] 租户列表 + 审批按钮 + 详情页
- [ ] Agent 评价看板四维指标可查
- [ ] 会话日志按租户/时间筛选
- [ ] 平台配置 CRUD 正常
- [ ] 知识管理界面可用（产品录入 + 冲突规则）

### PWA + widget

- [ ] PWA 安装可用
- [ ] widget.js 嵌入第三方可加载
