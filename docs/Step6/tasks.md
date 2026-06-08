# Step 6 消项清单

> 负责：前台 Agent + 配药师 + 问卷师 + 识肤师 + 日报官
> GitHub Issue: #1(部分), #5(部分), #17, #18, #19

---

## 🔴 Critical — #5(部分) (1 条)

- [x] **S6-01** `python-service/app/agents/orchestrator.py` + 各 Agent — `trigger_reflection_async()` 已定义但无任何 Agent 在 run() 完成时调用。需在 workshop/diagnosis/photo_analyst 的 run() 末尾加 `asyncio.create_task(trigger_reflection_async(...))` → **fixed**: 三个 Agent run() 末尾均添加了 `asyncio.create_task(trigger_reflection_async(ctx, result, "配药师/问卷师/识肤师"))`，fixes #5

---

## 🟠 High — #17, #18, #19 (5 条)

- [x] **S6-02** `python-service/app/agents/photo_analyst_agent.py:270` — 每次调用 `_call_vl_model` 创建新 `AsyncOpenAI()` 客户端。不复用 `llm_util.get_client()` 连接池 → **fixed**: 改为 `client = get_client()` 复用全局连接池，fixes #17
- [x] **S6-03** `python-service/app/agents/photo_analyst_agent.py:290` — VL 模型调用 `chat.completions.create()` 无 `asyncio.wait_for` 包装，可能永久挂起 → **fixed**: 添加 `asyncio.wait_for(..., timeout=30.0)` 包装，fixes #17
- [x] **S6-04** `python-service/app/agents/orchestrator.py` — 无 `stage == "escalated"` 检查。已转人工的 session 仍被 Agent 处理。入口处加 stage 判断 → **fixed**: `run_orchestrator()` 入口添加 escalated stage 检查，直接返回转人工提示，fixes #18
- [x] **S6-05** `python-service/app/agents/orchestrator.py` — 意图分类后无 escalation 触发检查。用户说"红肿过敏"照样派给配药师。子 Agent 启动前调 `escalation.check_escalation()` → **fixed**: `_delegate_to_agent()` 在正常委派前添加 `check_and_escalate()` 调用，命中则阻断并返回覆盖回复，fixes #18
- [x] **S6-06** `python-service/app/agents/copywriter_agent.py:277` — `resume()` 返回 "已根据您的反馈调整日程" 但不调 LLM 重新生成。真正调 LLM 重新生成 schedule → **fixed**: `resume()` 调整分支真正调用 `llm_chat()` 重新生成 schedule_card JSON，fixes #19

---

## 🟡 Medium (5 条)

- [x] **S6-07** `python-service/app/agents/interrupt_handler.py:95` — "推荐" 作为问卷退出关键词太宽泛。中途说 "请推荐适合我的护肤品" 就退出。移除或改模糊匹配 → **fixed**: 从 quit_keywords 列表移除 "推荐"，fixes #1
- [x] **S6-08** `python-service/app/agents/interrupt_handler.py` — 退出问卷前无用户二次确认。检测到退出关键词后加确认步骤 → **fixed**: `check_diagnosis_quit()` 添加二次确认逻辑（quit_pending 标记），routes.py 中首次触发发送确认提示，用户回复"是"才真正退出，fixes #1
- [x] **S6-09** `python-service/app/agents/diagnosis_agent.py` — 多选答案无合法性校验。A/B/C/D 以外的任意文本都被接受 → **fixed**: 添加答案校验，接受 A/B/C/D 字母或完整选项文本，非法输入返回提示不推进步骤，fixes #1
- [x] **S6-10** `python-service/app/agents/workshop_agent.py:370` — `resume()` 超时自动 resume 时 `ctx.input` 是 "继续（默认）" 而非原始用户查询，配药师用无意义 query 重跑 → **fixed**: 在 agent_state 中保存 `original_query`，resume 时优先使用它作为搜索输入，fixes #1
- [x] **S6-11** `python-service/app/agents/workshop_agent.py:252` — 产品价格/图片 enrichment 注释 "从 DB 获取" 但代码只复制 LLM 输出。price 默认 0，image_url 默认空字符串。实现实际 DB 查询 → **fixed**: 对每个产品 ID 查询 products 表获取真实 price 和 image_url，fixes #1

---

## 🟢 Low (8 条)

- [x] **S6-12** `python-service/app/agents/orchestrator.py:321` — 直接 Tool (product_add/knowledge_query) 绕过 stage 检查。`agent_running` 或 `agent_interrupted` session 也能收到直接 Tool 回复 → **fixed**: `run_orchestrator()` 入口统一检查所有 stage（escalated/agent_running/agent_interrupted），优先级在意图路由之前，fixes #1
- [x] **S6-13** `python-service/app/agents/orchestrator.py:149` — chat 意图绕过 interrupt 处理。`stage=="agent_interrupted"` 时发 chat 消息不调 `resume_agent`，interrupt 状态不清 → **fixed**: agent_interrupted 时先做意图分类，chat 意图直接清理中断状态（stage→idle），fixes #1
- [x] **S6-14** `python-service/app/agents/photo_analyst_agent.py` — 每次分析都创建 interrupt。即使分析结果简单也弹确认。减少不必要的 interrupt → **fixed**: 仅当 `concerns` 非空时才创建 deep_analysis interrupt，fixes #1
- [x] **S6-15** `python-service/app/agents/copywriter_agent.py` — 同上，每次生成 schedule 都创建 interrupt → **fixed**: 检测用户是否含调整关键词，若无且非直接确认指令才创建 schedule_adjust interrupt，fixes #1
- [x] **S6-16** `python-service/app/agents/photo_analyst_agent.py:221` — resume "不需要" 路径不写 fe_ingest 记录用户选择 → **fixed**: "不需要" 分支添加 `fe_ingest()` 记录用户拒绝深入分析的选择，fixes #1
- [x] **S6-17** `python-service/app/agents/copywriter_agent.py:71` — 时区计算用 `now.hour + 8`，无 timezone 库。改用 `zoneinfo` → **fixed**: 改用 `datetime.now(ZoneInfo("Asia/Shanghai"))`，fixes #1
- [x] **S6-18** `python-service/app/agents/photo_analyst_agent.py` — VL 模型调用无重试。API 返回 429 时直接失败 → **fixed**: `_call_vl_model()` 添加指数退避重试（1s/2s/4s），第 3 次失败抛出异常，fixes #1
- [x] **S6-19** `python-service/app/agents/llm_util.py` — `_now()` 在 llm_util 和每个 agent 文件中重复定义。统一为共享工具 → **fixed**: 创建 `app/agents/shared_util.py` 中的 `now_iso()`，所有 agent 的 `_now()` 改为委托调用，fixes #1
