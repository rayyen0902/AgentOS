# Step 8 消项清单

> 负责：Reflection Agent + Memory Consolidation + Human Escalation + Agent Journal + Evaluation
> GitHub Issue: #5(部分), #14, #16

---

## 🔴 Critical — #5(部分) (2 条)

- [x] **S8-01** `python-service/app/agents/reflection.py` — `trigger_reflection_async()` 虽已定义，但需确保函数签名稳定供 Step 6 调用。确认参数: `(session_ctx, agent_result)` → **已确认：签名 `(ctx: SessionContext, result: AgentResult, agent_name: str)` 与 Step 6 调用方一致，添加 docstring 说明稳定 API 契约**
- [x] **S8-02** `python-service/app/agents/reflection.py` — `Reflection` 返回类型 (dataclass) 从未在任何地方定义。定义: `satisfaction`/`lesson`/`rule_candidate`/`should_escalate` → **已确认：`Reflection` 已是正确 dataclass，包含全部 4 字段 + `risk_level` + `raw_analysis`**

---

## 🟠 High — #14, #16 (5 条)

- [x] **S8-03** `python-service/app/agents/evaluation.py` — `_calculate_accuracy` SQL 查询所有 reflections 不按 agent_name 过滤 → **已在 commit 6901686 修复：`event_data->>'agent_name' = $2` + `make_interval(days => $1)`**
- [x] **S8-04** `python-service/app/agents/evaluation.py` — `_calculate_conversion` SQL 同上，不按 agent_name 过滤 → **已修复：workshop 查询按 agent_name 过滤**
- [x] **S8-05** `python-service/app/agents/evaluation.py` — `_calculate_retention` SQL 同上，不按 agent_name 过滤 → **已修复：两个子查询均用 `WHERE current_agent = $1`**
- [x] **S8-06** `python-service/app/agents/evaluation.py` — `_calculate_trust` SQL 同上，不按 agent_name 过滤。四个方法接受参数但全不用→所有 Agent 得分一模一样 → **已修复：`event_data->>'agent_name' = $2`**
- [x] **S8-07** `python-service/app/agents/journal.py:64` — `_get_week_range()` 周日 00:00 触发时 `days_since_sunday=0`，窗口=本周日 00:00 到当前(~2min) 而非上周一整周。`days_since_sunday == 0` 时改为 7 → **已在 commit 6901686 修复：`if now.weekday() == 6: days_since_sunday = 7`**

---

## 🟡 Medium (5 条)

- [x] **S8-08** `python-service/app/agents/reflection.py:80` — 诊断 Reflection 条件检查 `state.phase` / `state.step`。实际 diagnosis_agent 存的是 `diagnosis_step`，永不会匹配。对齐字段名 → **已确认正确：`result.state.get("diagnosis_step", 0)` 已使用正确字段名，4 个回归测试覆盖此路径**
- [x] **S8-09** `python-service/app/agents/reflection.py:260` — audit log 的 `agent_name` 参数写死 `"reflection"` 而非实际 Agent 名。改为传入的 agent_name 变量 → **已确认：代码已是 `f"reflection:{agent_name}"`，测试断言 `"reflection:配药师"` 验证通过**
- [x] **S8-10** `python-service/app/agents/escalation.py:237` — `llm_verify_escalation` JSON 解析失败或 LLM 不可用时默认返回 True（确认升级）。LLM 临时故障导致误升级。改为 LLM 不可用时仅规则匹配 → **已确认：两个 except 块均返回 `False`（保守策略），`HumanEscalationEngine.check` 将 `is_confirmed=False` 处理为 NONE**
- [x] **S8-11** `python-service/app/agents/memory_consolidation.py` + `python-service/app/tools/consolidation.py` — 两套完全重复的 consolidation 实现。合并到 `agents/memory_consolidation.py` → **已确认：`app/tools/consolidation.py` 不存在（已删除），所有导入均指向 `app.agents.memory_consolidation`**
- [x] **S8-12** `python-service/app/agents/memory_consolidation.py:16` — 从 `fe_client` 直接 import 绕过 registry 层（无重试和 fallback）。改为走 registry。**⚠️ 二次修复: `check_semantic_similarity()` 第128行内部仍有 `from app.tools.fe_client import fe_retrieve`，绕过顶部 registry 导入。**
- [x] **S8-17** `python-service/app/agents/memory_consolidation.py:190` — `await fe_ingest(ingest_input)` 变量 `ingest_input` 从未定义，运行必抛 NameError。补充 `FEIngestInput(...)` 构造。
- [x] **S8-18** `python-service/app/agents/memory_consolidation.py:128` — `check_semantic_similarity()` 内部 `from app.tools.fe_client import fe_retrieve` 绕过 registry 层（无重试/fallback）。删除该行，复用顶部 `from app.tools.registry import fe_retrieve`。

---

## 🟢 Low (4 条)

- [x] **S8-13** `python-service/app/agents/journal.py` — SQL INTERVAL 用字符串拼接 `$1 || ' days'`。改用 `make_interval(days => $1)` → **已确认：无字符串拼接模式，所有查询均使用参数化的 `make_interval`**
- [x] **S8-14** `python-service/app/agents/evaluation.py:93` — INTERVAL 字符串拼接同上 → **已确认：全部 7 个时间范围查询均使用 `make_interval(days => $N)`**
- [x] **S8-15** `python-service/main.py:56` — `last_evaluation_day` 用 `now.day` 比较在跨月时逻辑脆弱 → **已确认：改用 `last_evaluation_date: str` 存储 `now.strftime("%Y-W%W")` ISO 周键，无跨月问题**
- [x] **S8-16** 定时任务基础设施 — Agent Journal "每周日 00:00 UTC" 未指定实现方式 (APScheduler? crontab?)。文档明确方案 → **已在 `journal.py` 文件头添加 docstring：推荐 APScheduler（开发）/ crontab（生产），当前手动触发**
