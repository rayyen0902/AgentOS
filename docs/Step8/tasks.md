# Step 8 消项清单

> 你负责：Reflection Agent + Memory Consolidation + Human Escalation + Agent Journal + Evaluation

---

## #5 部分归属 Step 8【Critical】Reflection Agent 从未被触发

**你的部分**: 确保 `trigger_reflection_async()` 可用且被正确调用。

**修复**:
1. 确认 `reflection.py` 中 `trigger_reflection_async(session_ctx, agent_result)` 函数签名稳定
2. 在 `reflection.py` 中补充 `Reflection` dataclass 定义（satisfaction/lesson/rule_candidate/should_escalate）
3. **协调 Step 6**: 各 Agent（workshop/diagnosis/photo_analyst）需在 run() 末尾调用此函数

---

## #14 【High】Agent evaluation 四个指标全部忽略 agent_name

**文件**: `python-service/app/agents/evaluation.py`

**问题**: `_calculate_accuracy` / `_calculate_conversion` / `_calculate_retention` / `_calculate_trust` 四个方法接受 `agent_name` 参数但在 SQL WHERE 中全不用。所有 Agent 得分一模一样。

**修复**: 每个 SQL 查询加 `AND agent_name = $N` 过滤条件。

---

## #16 【High】journal _get_week_range() 周日 00:00 取本周而非上周

**文件**: `python-service/app/agents/journal.py:64`

**问题**: 周日 00:00 UTC 触发时 `days_since_sunday = 0`，计算窗口 = 本周日 00:00 到当前(~2min)。

**修复**: 
```python
days_since_sunday = now.weekday()
if days_since_sunday == 0:  # 周日
    days_since_sunday = 7   # 回溯到上周
```

---

## 关联：中优先级

| 文件 | 问题 | 修复 |
|------|------|------|
| `reflection.py:80` | 诊断条件检查 `state.phase`/`state.step`，实际存的是 `diagnosis_step` | 对齐字段名 |
| `reflection.py:260` | audit log `agent_name` 写死 `"reflection"` | 改为实际 agent 名 |
| `escalation.py:237` | `llm_verify_escalation` 错误时默认返回 True | 改为 LLM 不可用时仅规则匹配 |
| `memory_consolidation.py` + `tools/consolidation.py` | 两套重复实现 | 合并到 agents/memory_consolidation.py |

---

## 关联：基础设施

- **定时任务**: Agent Journal 的"每周日 00:00 UTC"需指定实现方式（建议 Python APScheduler 或系统 crontab 触发 API）
