# Step 6：各 Agent 实现

> **上下文范围**：PRD 第 5（Agent 与 Tool 定义）、第 6 节（Agent 身份与能力注册中心）
> **前置依赖**：Step 2（BaseAgent 接口）、Step 5（Tool 层）
> **完成标准**：5 个 Agent 全部可用，意图路由准确，中断→恢复流程正常

---

## 6.1 并发控制规范

- 同一 session_id 同一时刻只允许一个 Agent 运行（`agent_lock:{session_id}` Redis 锁）
- 新消息到达时若 stage = `agent_running`：前台 Agent 回复"正在处理上一条，稍等~"，不启动新 Agent
- 新消息到达时若 stage = `agent_interrupted`：视为中断回复，路由至 `agent.resume()`

---

## 6.2 Agent 身份表（读 DB）

```sql
-- agent_identities 表结构（Step 1 已创建）
-- agent_id 格式："{agent_type}_tenant_{tenant_id}"
-- capabilities JSONB，如 '["recommend_product", "build_routine"]'
```

```json
{
  "agent_id": "workshop_tenant_1",
  "agent_type": "workshop",
  "persona": "资深护肤配药师",
  "display_name": "肤小护·配药喵",
  "tenant_id": 1,
  "memory_namespace": "tenant:1:agent:workshop",
  "capabilities": ["recommend_product", "build_routine", "check_conflicts"],
  "tone": "专业温暖",
  "custom_prompt": null,
  "version": "1.0.0"
}
```

---

## 6A：前台 Agent + 意图路由

### 职责

- 接收用户消息 → 意图分类 → 委派子 Agent 或直接回复
- 模型：Flash LLM
- 不可中断
- 不委派子 Agent 时自行回复

### 意图分类输出（JSON Only）

```json
{
  "intent": "recommend_product | skin_diagnosis | photo_analysis | daily_schedule | product_add | knowledge_query | chat",
  "confidence": 0.92,
  "sub_intent": "routine_build",
  "extracted_entities": {
    "skin_concern": "控油",
    "product_category": "洗面奶"
  },
  "immediate_reply": "收到，配药师正在为您挑选~"
}
```

若 confidence < 0.6，前台 Agent 直接对话澄清，不委派子 Agent。

### 路由表

```
用户消息 → 前台Agent(Flash) 分类 →
  ├─ "推荐/买什么/选哪个"            → 配药师 Agent
  ├─ "拍照/看皮肤/帮我看看"           → 识肤师 Agent
  ├─ "肤质检测/做问卷/测一测"         → 问卷师 Agent
  ├─ "日报/今天怎么护肤/明天"         → 日报官 Agent
  ├─ "录入/添加产品/我在用"           → product_crud Tool
  ├─ "什么是/成分/功效/适不适合"      → rag_search Tool
  └─ "聊天/问候/问进度"               → 前台Agent直出
```

### 子 Agent 超时

| Agent | 超时时间 | 超时后行为 |
|-------|---------|-----------|
| 前台 Agent | 3s | 返回兜底回复"稍后再试" + 记录告警 |
| 配药师 | 30s | 主动推送"分析超时，已记录，稍后重试" |
| 识肤师 | 30s | 同上 |
| 问卷师 | 600s（单步 30s） | 单步超时 → 重发当前问题 |
| 日报官 | 20s | 跳过本次推送，下次触发时重试 |

超时机制：Python 侧用 `asyncio.wait_for`；Go 侧用 `context.WithTimeout`。

---

## 6B：配药师 Agent（workshop）

### 职责

- 肤质 + 需求 → 产品匹配
- 模型：Pro LLM
- 可中断：可反调确认成分过敏

### 流程

```
1. fe_retrieve（语义 + 偏好 + 情节）
2. profile_query（肤质 + 在用产品）
3. rag_search（产品语义搜索 + 关键词过滤）
4. rag_conflict（成分冲突检测）
5. Pro LLM 匹配 → workshop_card
6. [中断] 成分过敏确认（如有风险成分）
7. fe_ingest（写记忆）
```

### 输出卡片 workshop_card

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

---

## 6C：问卷师 Agent（diagnosis）

### 职责

- 7 步肤质问诊 → 生成肤质报告
- 模型：Flash LLM
- 不可中断（轮内）
- done=false 时表示还需继续下一步

### 7 步状态机

每步一问一答，`done=false` 时返回当前步骤的提问，由前端展示后用户回复进入下一步。

完成后调用 `fe_ingest` 写入肤质档案，输出 `skin_report_card`。

### 输出卡片 skin_report_card

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

---

## 6D：识肤师 Agent（photo_analyst）

### 职责

- 照片 → 多维度皮肤分析
- 模型：VL（Vision Language）
- 可中断：可追问确认

### 边界处理

- 非人脸图片 → VL 判定非皮肤图片 → 回复"请上传面部清晰照片"
- 图片 > 10MB → 拒绝并提示重新上传

---

## 6E：日报官 Agent（copywriter）

### 职责

- 早晚日报生成 + 推送
- 模型：Flash LLM
- 可中断：可确认调整

### 卡片类型

- `schedule_card`：早晚护肤日程

---

## 6.6 边界条件与异常流

### 用户行为边界

| 场景 | 处理方式 |
|------|----------|
| 用户发消息时 Agent 正在运行 | 前台 Agent 回复"正在处理，稍等~"，丢弃该消息 |
| 用户连续发 5 条以上消息（被限流） | 返回 4291，前端提示"发送太频繁，请稍候" |
| 用户上传图片但识肤师不可用 | 前台 Agent 回复"图片分析暂时不可用，您可以描述皮肤状况" |
| 识肤师接收到非人脸图片 | 回复"请上传面部清晰照片" |
| 问卷师中途用户发其他消息 | 视为退出问卷 → SessionState 清空 agent_state |
| 中断超时（5min 用户未回复） | 使用 options[0] 作为默认答案继续，记录 `interrupt_timed_out=true` |

### 系统故障边界

| 故障场景 | 降级方案 |
|----------|----------|
| Redis 不可用 | SessionState 降级为纯 PG 读写 |
| FE gRPC 不可用 | fe_retrieve 返回空，fe_ingest 进入本地队列稍后重试 |
| Python Agent 层不可用 | Go 返回 SSE error 事件 |
| pgvector 索引损坏 | hybrid_search 降级为仅 keyword 检索 |
| LLM API 限流 | 指数退避重试（1s, 2s, 4s），第 3 次失败返回兜底回复 |

---

## 6.7 验收标准

### 前台 Agent

- [ ] 意图分类 7 种 intent 准确率 > 85%（人工抽检 50 条）
- [ ] confidence < 0.6 时直接对话澄清，不委派子 Agent
- [ ] 委派子 Agent 后立即返回 `immediate_reply`
- [ ] 3s 超时兜底回复生效

### 配药师

- [ ] fe_retrieve → profile_query → rag_search → rag_conflict → Pro LLM 匹配链路完整
- [ ] workshop_card 产品列表含 reason + key_ingredients
- [ ] 中断确认成分过敏 → resume → 继续推荐
- [ ] 30s 超时兜底生效

### 问卷师

- [ ] 7 步状态机正确流转
- [ ] done=false 时返回中间提问
- [ ] 完成 → skin_report_card + fe_ingest
- [ ] 单步 30s 超时 → 重发当前问题

### 识肤师

- [ ] VL 模型分析返回多维度结果
- [ ] 非人脸图片拒绝
- [ ] 图片 > 10MB 拒绝

### 日报官

- [ ] schedule_card 生成正确
- [ ] 20s 超时兜底生效
