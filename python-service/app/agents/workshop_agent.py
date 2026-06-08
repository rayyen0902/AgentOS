"""
配药师 Agent (workshop) — Step 6B

职责:
- 肤质 + 需求 → 产品匹配
- 模型: Pro LLM
- 可中断: 可反调确认成分过敏

流程:
1. fe_retrieve（语义 + 偏好 + 情节）
2. profile_query（肤质 + 在用产品）
3. rag_search（产品语义搜索 + 关键词过滤）
4. rag_conflict（成分冲突检测）
5. Pro LLM 匹配 → workshop_card
6. [中断] 成分过敏确认（如有风险成分）
7. fe_ingest（写记忆）
"""
import asyncio
import json
import logging
import time
from typing import Any

from app.agents.base import (
    AgentResult,
    BaseAgent,
    CardPayload,
    InterruptRequest,
    SessionContext,
    StatusEvent,
)
from app.agents.llm_util import llm_chat
from app.agents.tool_invoker import (
    fe_retrieve,
    fe_ingest,
    rag_search,
    rag_conflict,
    profile_query,
)
from config import settings

logger = logging.getLogger(__name__)

WORKSHOP_SYSTEM_PROMPT = """你是「肤小护·配药喵」，一个资深护肤配药师 AI Agent。

你的职责:
1. 根据用户的肤质、过敏情况、当前在用产品，推荐最适合的护肤品
2. 检查成分冲突，确保推荐不会与用户已有产品冲突
3. 给出使用建议和注意事项

输出必须是严格的 JSON 格式:
{
  "products": [
    {
      "id": <product_id>,
      "name": "产品名",
      "brand": "品牌",
      "category": "洗面奶/精华/面霜/防晒...",
      "price": <价格数字>,
      "reason": "推荐理由",
      "key_ingredients": ["成分1", "成分2"],
      "image_url": ""
    }
  ],
  "conflicts": [],
  "routine_tip": "使用建议"
}

注意:
- reason 必须以用户肤质和需求为依据
- 若有冲突成分，conflicts 列出具体冲突
- routine_tip 包含早晚使用顺序和注意事项
- 只推荐在产品知识库中实际存在的产品"""


class WorkshopAgent(BaseAgent):
    name = "workshop"

    async def run(self, ctx: SessionContext, input: str) -> AgentResult:
        events: list[StatusEvent] = []
        seq = 0
        t_start = time.time()

        memory_namespace = f"tenant:{ctx.tenant_id}:agent:workshop"
        products_list: list[dict] = []
        conflicts_list: list[dict] = []
        routine_tip = ""

        # ── Step 1: fe_retrieve ──
        seq += 1
        events.append(StatusEvent(
            seq=seq, source="tool:fe_retrieve",
            status="running", label="正在回忆您的偏好...",
            created_at=_now(),
        ))
        mem = await fe_retrieve(
            query=input,
            layer="all",
            n=5,
            user_id=ctx.user_id,
            namespace=memory_namespace,
        )
        events.append(StatusEvent(
            seq=seq, source="tool:fe_retrieve",
            status="done",
            label=f"记忆检索完成 (retrieved {mem.retrieved_count} 条)",
            duration_ms=int((time.time() - t_start) * 1000),
            created_at=_now(),
        ))

        # ── Step 2: profile_query ──
        seq += 1
        events.append(StatusEvent(
            seq=seq, source="tool:profile_query",
            status="running", label="正在查询您的肤质档案...",
            created_at=_now(),
        ))
        profile = await profile_query(user_id=ctx.user_id)
        events.append(StatusEvent(
            seq=seq, source="tool:profile_query",
            status="done",
            label=f"肤质档案: {profile.skin_type or '未知'} (完整度: {profile.profile_completeness:.0%})",
            created_at=_now(),
        ))

        # ── Step 3: rag_search ──
        seq += 1
        events.append(StatusEvent(
            seq=seq, source="tool:rag_search",
            status="running", label="正在匹配护肤产品...",
            created_at=_now(),
        ))
        search_result = await rag_search(
            query=input,
            tenant_id=ctx.tenant_id,
            top_k=5,
            search_type="hybrid",
        )
        events.append(StatusEvent(
            seq=seq, source="tool:rag_search",
            status="done",
            label=f"产品检索完成 (共 {search_result.total} 条)",
            created_at=_now(),
        ))

        # ── Step 4: rag_conflict ──
        seq += 1
        events.append(StatusEvent(
            seq=seq, source="tool:rag_conflict",
            status="running", label="正在检查成分冲突...",
            created_at=_now(),
        ))

        # 收集所有 ingredient 进行冲突检测
        all_ingredients: list[str] = []
        for item in search_result.items:
            all_ingredients.extend(item.ingredients)
        # 去重
        all_ingredients = list(set(all_ingredients))

        conflict_result = await rag_conflict(
            ingredients=all_ingredients,
            user_id=ctx.user_id,
        )
        conflicts_list = [
            {
                "conflict_type": c.conflict_type,
                "severity": c.severity,
                "description": c.description,
                "ingredients_involved": c.ingredients_involved,
                "suggestion": c.suggestion,
            }
            for c in conflict_result.conflicts
        ]
        events.append(StatusEvent(
            seq=seq, source="tool:rag_conflict",
            status="done",
            label=f"冲突检测完成: {'有高风险冲突!' if conflict_result.has_urgent else '未发现高风险冲突'}",
            created_at=_now(),
        ))

        # ── Step 5: Pro LLM 匹配 → workshop_card ──
        seq += 1
        events.append(StatusEvent(
            seq=seq, source="agent:workshop",
            status="running", label="配药师正在为您精心挑选...",
            created_at=_now(),
        ))

        user_prompt = f"""用户需求: {input}

用户肤质档案:
- 肤质: {profile.skin_type or '未知'}
- 关注问题: {', '.join(profile.skin_concerns) if profile.skin_concerns else '无'}
- 过敏: {', '.join(profile.allergies) if profile.allergies else '无'}
- 当前在用产品: {json.dumps(profile.current_products, ensure_ascii=False) if profile.current_products else '无'}

用户历史记忆:
{mem.content if mem.content else '无历史记忆'}

可推荐产品池:
{json.dumps([{
    'id': item.id,
    'name': item.name,
    'brand': item.brand,
    'category': item.category,
    'ingredients': item.ingredients,
    'description': item.description,
} for item in search_result.items], ensure_ascii=False)}

成分冲突报告:
{json.dumps(conflicts_list, ensure_ascii=False) if conflicts_list else '无冲突'}

请基于以上信息，为用户推荐 1-3 款最适合的产品，输出严格的 workshop_card JSON 格式。"""

        try:
            llm_raw = await llm_chat(
                model=settings.LLM_PRO_MODEL,
                system_prompt=WORKSHOP_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                timeout_s=25.0,
                json_mode=True,
                temperature=0.3,
                max_tokens=2048,
            )
            card_data = json.loads(llm_raw)
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"[workshop] LLM parse failed: {e}")
            # 兜底: 直接用 RAG 结果构造卡片
            card_data = {
                "products": [
                    {
                        "id": item.id,
                        "name": item.name,
                        "brand": item.brand,
                        "category": item.category,
                        "price": 0,
                        "reason": f"基于「{input}」的匹配结果",
                        "key_ingredients": item.ingredients[:5],
                        "image_url": "",
                    }
                    for item in search_result.items[:3]
                ],
                "conflicts": conflicts_list,
                "routine_tip": "建议先进行皮肤测试，确认无不适后再全脸使用。",
            }

        products_list = card_data.get("products", [])
        conflicts_list = card_data.get("conflicts", conflicts_list)
        routine_tip = card_data.get("routine_tip", "")

        # 补充产品额外信息 (S6-11: 从 DB 查询真实 price/image_url)
        enriched_products: list[dict] = []
        for product in products_list:
            enriched = {
                "id": product.get("id", 0),
                "name": product.get("name", ""),
                "brand": product.get("brand", ""),
                "category": product.get("category", ""),
                "price": product.get("price", 0),
                "reason": product.get("reason", ""),
                "key_ingredients": product.get("key_ingredients", []),
                "image_url": product.get("image_url", ""),
            }
            # S6-11: 从 DB 查询产品附加信息（价格、图片）
            pid = enriched["id"]
            if pid and pid > 0:
                try:
                    from db_util import db
                    row = await db.fetchrow(
                        "SELECT price, image_url FROM products WHERE id = $1",
                        pid,
                    )
                    if row:
                        if enriched["price"] == 0:
                            enriched["price"] = float(row.get("price") or 0)
                        if not enriched["image_url"]:
                            enriched["image_url"] = row.get("image_url") or ""
                except Exception as db_err:
                    logger.warning(f"[workshop] DB enrichment for product {pid}: {db_err}")
            enriched_products.append(enriched)

        card = CardPayload(
            type="workshop_card",
            data={
                "products": enriched_products,
                "conflicts": conflicts_list,
                "routine_tip": routine_tip,
            },
        )

        events.append(StatusEvent(
            seq=seq, source="agent:workshop",
            status="done",
            label=f"推荐完成 ({len(enriched_products)} 款产品)",
            duration_ms=int((time.time() - t_start) * 1000),
            created_at=_now(),
        ))

        # ── Step 6: [中断] 成分过敏确认 ──
        interrupt = None
        if conflict_result.has_urgent:
            risk_conflicts = [c for c in conflict_result.conflicts if c.severity == "high"]
            risk_ingredients = list(set(
                ing for c in risk_conflicts for ing in c.ingredients_involved
            ))
            conflict_desc = "; ".join(
                f"{c.description} (建议: {c.suggestion})" for c in risk_conflicts[:3]
            )
            interrupt = InterruptRequest(
                type="allergy_check",
                question=f"检测到以下成分可能与您的肤质存在冲突: {', '.join(risk_ingredients[:5])}。{conflict_desc}。是否仍然继续推荐？",
                options=["继续推荐", "排除这些成分重新推荐"],
                timeout_s=300,
                created_at=_now(),
            )
            events.append(StatusEvent(
                seq=seq + 1, source="agent:workshop",
                status="done",
                label="等待用户确认成分过敏",
                created_at=_now(),
            ))

        # ── Step 7: fe_ingest ──
        if not interrupt:
            # 只有不中断时才写记忆（中断时等 resume 再写）
            await fe_ingest(
                text=f"[user] {input} | [assistant] 推荐了 {len(enriched_products)} 款产品",
                role="assistant",
                session_id=ctx.session_id,
                user_id=ctx.user_id,
                namespace=memory_namespace,
                importance=0.7,
            )

        # ── S6-01: 异步触发 Reflection ──
        result = AgentResult(
            state={
                "phase": "interrupted" if interrupt else "completed",
                "step": 7,
                "current_agent": "workshop",
                "original_query": input,  # S6-10: 保存原始 query 供 resume 使用
            },
            reply=reply,
            interrupt=interrupt,
            events=events,
            card=card,
            done=interrupt is None,
        )
        import asyncio as _asyncio
        from app.agents.reflection import trigger_reflection_async as _ref_async
        _asyncio.create_task(_ref_async(ctx, result, "配药师"))
        return result

    async def resume(self, ctx: SessionContext, reply: str) -> AgentResult:
        """中断恢复: 用户确认成分过敏 → 重新推荐或继续"""
        events: list[StatusEvent] = []
        seq = 0

        # 检查用户选择 (S6-10: 超时自动 resume 用"继续（默认）"时不走排除分支)
        is_default_resume = reply == "继续（默认）" or reply == "继续"
        exclude_conflicts = not is_default_resume and ("排除" in reply or "重新推荐" in reply)

        if exclude_conflicts:
            # 重新搜索，排除冲突成分
            events.append(StatusEvent(
                seq=0, source="agent:workshop",
                status="running", label="正在排除冲突成分，重新推荐...",
                created_at=_now(),
            ))

            # S6-10: 使用 ctx.input 原始用户需求（非"继续（默认）"）
            original_input = ctx.agent_state.get("original_query", ctx.input)
            modified_input = f"{original_input} (排除高风险冲突成分)"
            result = await self.run(ctx, modified_input)
            result.events = events + result.events
            return result

        # 用户确认继续 → 写入记忆
        events.append(StatusEvent(
            seq=0, source="agent:workshop",
            status="running", label="已确认，执行推荐...",
            created_at=_now(),
        ))

        memory_namespace = f"tenant:{ctx.tenant_id}:agent:workshop"
        await fe_ingest(
            text=f"[user] 确认成分风险，已选择继续推荐 | [interrupt] allergy_check confirmed",
            role="assistant",
            session_id=ctx.session_id,
            user_id=ctx.user_id,
            namespace=memory_namespace,
            importance=0.6,
        )

        events.append(StatusEvent(
            seq=1, source="agent:workshop",
            status="done", label="过敏确认已记录，推荐已提交",
            created_at=_now(),
        ))

        return AgentResult(
            state={"phase": "completed", "step": 7, "current_agent": None},
            reply="已确认，推荐的产品已为您准备好，使用时请注意观察皮肤反应哦~",
            events=events,
            done=True,
        )


def _now() -> str:
    from app.agents.shared_util import now_iso
    return now_iso()
