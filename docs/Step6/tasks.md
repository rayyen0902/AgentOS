# Step 6 消项清单

> 你负责：前台 Agent + 配药师 + 问卷师 + 识肤师 + 日报官

---

## #5 部分归属 Step 6【Critical】Reflection Agent 从未被触发

**你的部分**: 以下 Agent 完成工作后需调用 `trigger_reflection_async()`:
- `workshop_agent.py` — `run()` 末尾（workshop_card 推送后）
- `diagnosis_agent.py` — `run()` 末尾（skin_report_card 推送后）
- `photo_analyst_agent.py` — `run()` 末尾

**协调**: Step 8 需确保 `trigger_reflection_async()` 存在且可用。

---

## #17 【High】VL 模型调用无 timeout + 每次创建新客户端

**文件**: `python-service/app/agents/photo_analyst_agent.py`

**修复**:
1. **行 270**: 不每次 new `AsyncOpenAI()`——复用 `llm_util.get_client()`
2. **行 290**: 加 `asyncio.wait_for(..., timeout=25.0)`（留 5s 余量给 30s 总超时）

---

## #18 【High】无 escalated 检查 + 无 escalation 触发

**文件**: `python-service/app/agents/orchestrator.py`

**修复**:
1. `run_orchestrator()` 入口加 `stage == "escalated"` 检查——已升级 session 只记录消息不处理
2. 意图分类后、子 Agent 启动前，调用 `escalation.check_escalation()` 检测升级关键词

---

## #19 【High】copywriter resume() 不调 LLM + interrupt_handler "推荐" 误触

**文件**: 
- `python-service/app/agents/copywriter_agent.py:277`
- `python-service/app/agents/interrupt_handler.py:95`

**修复**:
1. `copywriter_agent.resume()` — 用户确认调整后真正调 LLM 重新生成 schedule
2. `interrupt_handler.py` — 把 `"推荐"` 移除出诊断退出关键词，或改为需上下文确认的模糊匹配

---

## #5 关联: 确保各 Agent 的超时机制正确

每个 Agent 的 `run()` 应由 routes.py 用对应超时包装（不在本 Step 范围），但 Agent 内部不应自己再包超时。确认：
- `workshop_agent.py` — 无内部超时，由外层 30s 控制
- `diagnosis_agent.py` — 单步逻辑本身应 < 30s
- `photo_analyst_agent.py` — VL 调用加 25s timeout（如上 #17）
- `copywriter_agent.py` — 无内部超时，由外层 20s 控制

---

## 关联：低优先级

- `interrupt_handler.py` 退出问卷前加用户二次确认
- `diagnosis_agent.py` 多选答案加合法性校验
- `photo_analyst_agent.py` / `copywriter_agent.py` — 减不必要的 interrupt（每次都弹确认体验差）
