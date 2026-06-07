# Step 8：运营闭环

> **上下文范围**：PRD 第 7.4（Memory Consolidation）、第 8 节（Agent 自进化与运营闭环）、第 8.5（Human Escalation）
> **前置依赖**：Step 5（Tool 层，含 fe_ingest）、Step 6（配药师/问卷师/识肤师 Agent 可用）、Step 2（Telemetry 基础）
> **完成标准**：Reflection Agent 异步运行，Human Escalation 规则引擎触发正确，Agent Journal 定时任务可用

---

## 8.1 Reflection Agent

### 触发条件

| 条件 | 是否触发 Reflection |
|------|-------------------|
| 配药师 workshop_card 推送完成 | 是 |
| 识肤师 skin_report_card 推送完成 | 是 |
| 问卷师 7 步完成 | 是 |
| 前台 Agent 直出（无子 Agent） | 否 |
| Agent 超时/报错 | 否（记录 Observation 即可） |

### 实现

```python
class ReflectionAgent(BaseAgent):
    async def reflect(self, session: SessionContext, result: AgentResult) -> Reflection:
        analysis = await self.llm.analyze(
            user_message=session.input,
            agent_response=result.reply,
            tools_called=result.tool_calls,
            outcome=session.outcome,
        )
        return Reflection(
            satisfaction=analysis.satisfaction,
            lesson=analysis.lesson,
            rule_candidate=analysis.new_rule,
            should_escalate=analysis.risk_level == "high",
        )
```

- **模型**：Pro LLM
- **运行方式**：`asyncio.create_task`，不阻塞主流程
- **失败处理**：Reflection 失败不影响用户体验，只记录日志
- **输出**：写入 `agent_audit_log` 表

---

## 8.2 Memory Consolidation

- **触发时机**：Reflection Agent 完成后异步触发
- **窗口**：7 天内出现 ≥ 3 次的相同语义事实 → 从 Episodic 提升至 Semantic
- **写入**：通过 `fe_ingest` Tool，`importance = 0.8`
- **去重**：相同 namespace + 相似度 > 0.95 的 Semantic 条目合并（FE 侧负责）

---

## 8.3 Human Escalation 规则引擎

### 升级规则

```python
ESCALATION_RULES = [
    {"condition": "过敏反应描述（红肿/刺痛/起疹）", "level": "urgent",   "action": "转人工 + 站内告警"},
    {"condition": "烂脸/严重不良反应",             "level": "emergency", "action": "转人工 + 电话/短信通知"},
    {"condition": "投诉/退款/法律威胁",             "level": "high",     "action": "转人工客服"},
    {"condition": "医疗建议请求（处方药/皮肤病）",   "level": "high",     "action": "拒答 + 建议就医"},
    {"condition": "成分过敏确认",                   "level": "medium",   "action": "中断 + 人工确认"},
]
```

### 执行细节

- **检测时机**：前台 Agent 意图分类完成后，子 Agent 启动前
- **检测方式**：规则匹配（关键词 + 正则）+ Flash LLM 二次确认（高敏感场景）
- **转人工后**：SessionState.stage → `escalated`，不再接受 Agent 处理，只记录消息
- **恢复**：管理员在后台手动将 stage 重置为 `idle`

---

## 8.4 Agent Journal（成长日志）

- **触发**：每周日 00:00 UTC 定时任务（Cron）
- **内容**：
  - 本周服务用户数 / 推荐次数
  - 采纳率（选购/下单）
  - 高频需求 Top3
  - 新发现（Reflection 汇总）
  - 策略调整建议
- **输出**：写入 `agent_audit_log` + 通知管理员

---

## 8.5 Observation Layer 告警规则

| 指标 | 阈值 | 告警级别 | 动作 |
|------|------|---------|------|
| 任意 Tool 失败率 | > 10% / 5min | WARNING | 站内通知 |
| Agent 整体失败率 | > 5% / 5min | ERROR | 站内 + 短信 |
| LLM p95 延迟 | > 8s | WARNING | 站内通知 |
| FE gRPC 错误率 | > 20% / 5min | CRITICAL | 站内 + 短信 + 自动降级（无记忆模式） |

---

## 8.6 Agent 评价体系

| 维度 | 定义 | 数据来源 |
|------|------|----------|
| Accuracy | 推荐产品是否匹配肤质 | Reflection Agent + 选购率 |
| Conversion | 推荐→选购/下单转化 | 选购回调 + 订单数据 |
| Retention | 用户 7 日内回访率 | 会话日志 |
| Trust | 采纳率 / 追问率 | Reflection Agent 评估 |

---

## 8.7 验收标准

### Reflection

- [ ] 配药师完成 → Reflection 异步执行
- [ ] 问卷师完成 → Reflection 异步执行
- [ ] 识肤师完成 → Reflection 异步执行
- [ ] 前台 Agent 直出不触发 Reflection
- [ ] Reflection 失败不影响主流程
- [ ] Reflection 结果写入 `agent_audit_log`

### Memory Consolidation

- [ ] 相同语义事实 ≥ 3 次 → 自动提升至 Semantic
- [ ] `importance = 0.8` 正确写入

### Human Escalation

- [ ] "红肿/刺痛" → urgent 级别触发
- [ ] "烂脸" → emergency 级别触发
- [ ] "退款/投诉" → high 级别触发
- [ ] "处方药" → 拒答 + 建议就医
- [ ] stage → `escalated` 后不再接受 Agent 处理
- [ ] 管理员可重置 stage → `idle`

### Agent Journal

- [ ] 定时任务每周日 00:00 UTC 触发
- [ ] 包含 5 项内容（用户数/采纳率/高频需求/新发现/建议）
- [ ] 写入 `agent_audit_log`

### Observation 告警

- [ ] Tool 失败率 > 10% → WARNING
- [ ] Agent 失败率 > 5% → ERROR
- [ ] LLM p95 > 8s → WARNING
- [ ] FE gRPC > 20% → CRITICAL
