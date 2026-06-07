"""
问卷师 Agent (diagnosis) — Step 6C

职责:
- 7 步肤质问诊 → 生成肤质报告
- 模型: Flash LLM
- 不可中断（轮内）
- done=false 时表示还需继续下一步

7 步状态机，每步一问一答，done=false 时返回当前步骤的提问。
完成后调用 fe_ingest 写入肤质档案，输出 skin_report_card。
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
    SessionContext,
    StatusEvent,
)
from app.agents.llm_util import llm_chat
from app.agents.tool_invoker import fe_ingest
from config import settings

logger = logging.getLogger(__name__)

# ── 7 步问题定义 ──
DIAGNOSIS_STEPS = [
    {
        "step": 1,
        "key": "oil_level",
        "question": "第 1/7 步：您日常的皮肤出油情况如何？",
        "options": [
            "全脸都很油，半天就反光",
            "T区（额头鼻子）油，脸颊正常",
            "基本不油，有时还觉得干",
            "看季节，夏天油冬天干",
        ],
    },
    {
        "step": 2,
        "key": "sensitivity",
        "question": "第 2/7 步：您的皮肤敏感情况？",
        "options": [
            "很容易泛红、刺痛，用什么都小心",
            "换季时会有些敏感",
            "偶尔会，大多数时候没事",
            "从来没敏感过，很耐受",
        ],
    },
    {
        "step": 3,
        "key": "hydration",
        "question": "第 3/7 步：皮肤的水润感如何？",
        "options": [
            "洗完脸 5 分钟就紧绷起皮",
            "偶尔会觉得干，特别是冬天",
            "平时还好，但上妆会卡粉",
            "一直很水润，不觉得干",
        ],
    },
    {
        "step": 4,
        "key": "pigmentation",
        "question": "第 4/7 步：您有色斑或痘印困扰吗？",
        "options": [
            "有明显的色斑/晒斑",
            "痘印很多，很久不消",
            "只有几颗淡淡的印记",
            "基本没有色素问题",
        ],
    },
    {
        "step": 5,
        "key": "pores",
        "question": "第 5/7 步：毛孔状态如何？",
        "options": [
            "毛孔粗大，特别是在 T 区",
            "鼻头有黑头，其他还好",
            "毛孔细腻，不太明显",
            "没太注意过毛孔问题",
        ],
    },
    {
        "step": 6,
        "key": "allergy_history",
        "question": "第 6/7 步：您对哪些成分过敏或不适？",
        "options": [
            "酒精类产品会刺痛",
            "香精/防腐剂容易过敏",
            "酸类（水杨酸/果酸）不耐受",
            "没有已知过敏成分",
        ],
    },
    {
        "step": 7,
        "key": "lifestyle",
        "question": "第 7/7 步：以下哪个最符合您的生活状态？",
        "options": [
            "经常熬夜，作息不规律",
            "压力大，饮食偏油腻/甜",
            "作息规律，饮食健康",
            "不固定，看情况",
        ],
    },
]

DIAGNOSIS_SYSTEM_PROMPT = """你是「肤小护·问卷师」，一个专业的皮肤检测 AI Agent。

根据用户的 7 步问答结果，分析肤质并生成 skin_report_card JSON。

skin_report_card 输出格式:
{
  "skin_type": "干性/油性/混合偏油/混合偏干/中性/敏感性",
  "dimensions": {
    "oil_level": 1-5,
    "sensitivity": 1-5,
    "hydration": 1-5,
    "pigmentation": 1-5,
    "pores": 1-5,
    "allergy_risk": 1-5,
    "lifestyle_impact": 1-5
  },
  "concerns": ["问题1", "问题2"],
  "recommendations": ["建议1", "建议2"],
  "generated_at": "ISO 时间戳"
}

- oil_level: 1=极干, 5=极油
- sensitivity: 1=不敏感, 5=极敏感
- hydration: 1=极度缺水, 5=水润
- pigmentation: 1=无色素, 5=严重色素
- pores: 1=细腻, 5=粗大
- allergy_risk: 1=无风险, 5=高风险
- lifestyle_impact: 1=无影响, 5=影响大

根据用户答案推断分数和肤质类型，concerns 列出 1-3 个主要问题，
recommendations 给出 2-3 条护肤建议。"""


class DiagnosisAgent(BaseAgent):
    name = "diagnosis"

    async def run(self, ctx: SessionContext, input: str) -> AgentResult:
        events: list[StatusEvent] = []
        t_start = time.time()

        # 从 agent_state 读取当前步骤
        current_step = ctx.agent_state.get("diagnosis_step", 0)
        answers: dict[str, str] = ctx.agent_state.get("diagnosis_answers", {})

        # 如果不是第一步，记录当前步骤的答案
        if current_step > 0 and current_step <= len(DIAGNOSIS_STEPS):
            step_key = DIAGNOSIS_STEPS[current_step - 1]["key"]
            answers[step_key] = input

        # 行进到下一步
        current_step += 1

        if current_step > len(DIAGNOSIS_STEPS):
            # 全部完成 → 生成 skin_report_card
            return await self._generate_report(ctx, answers, events, t_start)

        # 返回当前步骤的问题
        step_info = DIAGNOSIS_STEPS[current_step - 1]
        options_text = "\n".join(
            f"{chr(65 + i)}. {opt}" for i, opt in enumerate(step_info["options"])
        )
        question_text = f"{step_info['question']}\n\n{options_text}"

        events.append(StatusEvent(
            seq=current_step,
            source="agent:diagnosis",
            status="running" if current_step < len(DIAGNOSIS_STEPS) else "done",
            label=f"肤质问诊: 第 {current_step}/7 步",
            created_at=_now(),
        ))

        return AgentResult(
            state={
                "diagnosis_step": current_step,
                "diagnosis_answers": answers,
                "current_agent": "diagnosis",
                "step_started_at": _now(),
            },
            reply=question_text,
            events=events,
            done=False,  # 还需继续
        )

    async def resume(self, ctx: SessionContext, reply: str) -> AgentResult:
        """问卷师不可中断（轮内），但保留 resume 入口"""
        return await self.run(ctx, reply)

    async def _generate_report(
        self, ctx: SessionContext, answers: dict,
        events: list[StatusEvent], t_start: float,
    ) -> AgentResult:
        """根据 7 步答案生成 skin_report_card"""
        events.append(StatusEvent(
            seq=8, source="agent:diagnosis",
            status="running", label="正在生成肤质报告...",
            created_at=_now(),
        ))

        # 构造 LLM prompt
        answers_text = "\n".join(
            f"步骤 {i + 1} ({DIAGNOSIS_STEPS[i]['key']}): {answers.get(DIAGNOSIS_STEPS[i]['key'], '未回答')}"
            for i in range(len(DIAGNOSIS_STEPS))
        )

        user_prompt = f"""用户 7 步肤质问诊答案:

{answers_text}

请根据以上答案生成 skin_report_card JSON。"""

        try:
            llm_raw = await llm_chat(
                model=settings.LLM_FLASH_MODEL,
                system_prompt=DIAGNOSIS_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                timeout_s=25.0,
                json_mode=True,
                temperature=0.3,
                max_tokens=1024,
            )
            report = json.loads(llm_raw)
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"[diagnosis] LLM parse failed: {e}")
            # 兜底: 构造基础报告
            report = {
                "skin_type": "混合型",
                "dimensions": {
                    "oil_level": 3,
                    "sensitivity": 2,
                    "hydration": 3,
                    "pigmentation": 2,
                    "pores": 3,
                    "allergy_risk": 2,
                    "lifestyle_impact": 3,
                },
                "concerns": ["待进一步确认"],
                "recommendations": ["建议进行专业皮肤检测"],
                "generated_at": _now(),
            }

        # 确保必要字段
        report.setdefault("skin_type", "未知")
        report.setdefault("dimensions", {})
        report.setdefault("concerns", [])
        report.setdefault("recommendations", [])
        report.setdefault("generated_at", _now())

        # 构造 card
        card = CardPayload(
            type="skin_report_card",
            data=report,
        )

        # 写入记忆
        memory_namespace = f"tenant:{ctx.tenant_id}:agent:diagnosis"
        await fe_ingest(
            text=json.dumps({
                "answers": answers,
                "report": report,
            }, ensure_ascii=False),
            role="assistant",
            session_id=ctx.session_id,
            user_id=ctx.user_id,
            namespace=memory_namespace,
            importance=0.8,
        )

        events.append(StatusEvent(
            seq=9, source="agent:diagnosis",
            status="done",
            label=f"肤质报告生成完成: {report['skin_type']}",
            duration_ms=int((time.time() - t_start) * 1000),
            created_at=_now(),
        ))

        # 构造自然语言回复
        reply_lines = [
            f"✨ 肤质分析报告",
            f"",
            f"**肤质类型**: {report['skin_type']}",
        ]
        if report.get("concerns"):
            reply_lines.append(f"**主要问题**: {', '.join(report['concerns'])}")
        if report.get("recommendations"):
            reply_lines.append(f"**护肤建议**:")
            for rec in report["recommendations"]:
                reply_lines.append(f"  • {rec}")

        return AgentResult(
            state={
                "diagnosis_step": 7,
                "diagnosis_answers": answers,
                "current_agent": None,
            },
            reply="\n".join(reply_lines),
            events=events,
            card=card,
            done=True,
        )


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
