"""
识肤师 Agent (photo_analyst) — Step 6D

职责:
- 照片 → 多维度皮肤分析
- 模型: VL (Vision Language)
- 可中断: 可追问确认

边界处理:
- 非人脸图片 → VL 判定非皮肤图片 → 回复"请上传面部清晰照片"
- 图片 > 10MB → 拒绝并提示重新上传
"""
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
from app.agents.tool_invoker import fe_ingest
from config import settings

logger = logging.getLogger(__name__)

VL_SYSTEM_PROMPT = """你是「肤小护·识肤师」，一个专业的 AI 皮肤图像分析师。

根据用户上传的面部照片，分析皮肤状况并输出严格的 JSON 格式:

{
  "is_face": true/false,
  "face_detected": "描述检测到的面部信息",
  "skin_analysis": {
    "overall_condition": "整体状况描述",
    "oil_level": 1-5,
    "hydration": 1-5,
    "pores": 1-5,
    "pigmentation": 1-5,
    "redness": 1-5,
    "texture": 1-5,
    "acne": 1-5
  },
  "concerns": ["发现的问题1", "问题2"],
  "recommendations": ["建议1", "建议2"]
}

- 若照片中没有清晰的人脸，将 is_face 设为 false，并在 face_detected 中说明原因
- 各维度 1-5 分，越高越严重
- concerns 列出 1-3 个最显著的皮肤问题
- recommendations 给出 2-3 条针对性护肤建议"""


class PhotoAnalystAgent(BaseAgent):
    name = "photo_analyst"

    async def run(self, ctx: SessionContext, input: str) -> AgentResult:
        events: list[StatusEvent] = []
        seq = 0
        t_start = time.time()

        # ── 边界检查: 图片 > 10MB ──
        # image_size 由上游 Go 层或前端提供，放在 agent_state 中
        image_size_bytes = ctx.agent_state.get("image_size", 0)
        if image_size_bytes > 10 * 1024 * 1024:
            events.append(StatusEvent(
                seq=0, source="agent:photo_analyst",
                status="error", label="图片过大",
                created_at=_now(),
            ))
            return AgentResult(
                state={"phase": "rejected", "reason": "image_too_large"},
                reply="图片文件过大（超过 10MB），请压缩后重新上传~",
                events=events,
                done=True,
            )

        image_url = ctx.image_url or ctx.agent_state.get("image_url", "")
        if not image_url:
            return AgentResult(
                state={"phase": "error"},
                reply="未检测到图片，请上传面部清晰照片~",
                events=events,
                done=True,
            )

        # ── VL 模型分析 ──
        seq += 1
        events.append(StatusEvent(
            seq=seq, source="agent:photo_analyst",
            status="running", label="正在进行皮肤图像分析...",
            created_at=_now(),
        ))

        # VL 调用: 使用 vision-capable model，将图片 URL 传入
        user_prompt = f"请分析这张面部照片的皮肤状况。用户描述: {input or '无额外描述'}"
        try:
            llm_raw = await self._call_vl_model(image_url, user_prompt)
            analysis = json.loads(llm_raw)
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"[photo_analyst] VL call failed: {e}")
            return AgentResult(
                state={"phase": "error"},
                reply="图片分析暂时不可用，您可以描述皮肤状况，我来帮您分析~",
                events=events,
                done=True,
                error=str(e),
            )

        # ── 边界检查: 非人脸图片 ──
        if not analysis.get("is_face", False):
            face_info = analysis.get("face_detected", "未检测到人脸")
            events.append(StatusEvent(
                seq=seq, source="agent:photo_analyst",
                status="done", label=f"非人脸图片: {face_info}",
                created_at=_now(),
            ))
            return AgentResult(
                state={"phase": "rejected", "reason": "not_face"},
                reply="请上传面部清晰照片，我需要看到您的脸部才能进行皮肤分析哦~",
                events=events,
                done=True,
            )

        # ── 分析成功 ──
        skin = analysis.get("skin_analysis", {})
        concerns = analysis.get("concerns", [])
        recommendations = analysis.get("recommendations", [])

        events.append(StatusEvent(
            seq=seq, source="agent:photo_analyst",
            status="done",
            label=f"皮肤分析完成: 综合评分 {skin.get('overall_condition', '未知')}",
            duration_ms=int((time.time() - t_start) * 1000),
            created_at=_now(),
        ))

        # 构造 card
        card = CardPayload(
            type="skin_report_card",
            data={
                "skin_type": skin.get("overall_condition", ""),
                "dimensions": {
                    "oil_level": skin.get("oil_level", 3),
                    "sensitivity": skin.get("redness", 2),
                    "hydration": skin.get("hydration", 3),
                    "pigmentation": skin.get("pigmentation", 2),
                    "pores": skin.get("pores", 3),
                    "acne": skin.get("acne", 2),
                    "texture": skin.get("texture", 3),
                },
                "concerns": concerns,
                "recommendations": recommendations,
                "generated_at": _now(),
            },
        )

        # 构造回复
        reply_lines = [
            "📸 皮肤图像分析结果",
            "",
            f"**综合评估**: {skin.get('overall_condition', '无法判断')}",
        ]
        if concerns:
            reply_lines.append(f"**关注问题**:")
            for c in concerns[:3]:
                reply_lines.append(f"  • {c}")
        if recommendations:
            reply_lines.append(f"**建议**:")
            for r in recommendations[:3]:
                reply_lines.append(f"  • {r}")

        # 可中断: 确认是否深入分析
        interrupt = InterruptRequest(
            type="deep_analysis",
            question="是否需要我针对某个具体问题进行更深入的分析？（如：毛孔、色斑、出油等）",
            options=["深入分析毛孔问题", "深入分析色素问题", "深入分析出油问题", "不需要，这样就好"],
            timeout_s=300,
            created_at=_now(),
        )

        events.append(StatusEvent(
            seq=seq + 1, source="agent:photo_analyst",
            status="done", label="等待用户确认是否深入分析",
            created_at=_now(),
        ))

        # 写入记忆
        memory_namespace = f"tenant:{ctx.tenant_id}:agent:photo_analyst"
        await fe_ingest(
            text=json.dumps({"analysis": analysis, "image_url": image_url}, ensure_ascii=False),
            role="assistant",
            session_id=ctx.session_id,
            user_id=ctx.user_id,
            namespace=memory_namespace,
            importance=0.7,
        )

        return AgentResult(
            state={
                "phase": "interrupted",
                "current_agent": "photo_analyst",
                "analysis": analysis,
            },
            reply="\n".join(reply_lines),
            interrupt=interrupt,
            events=events,
            card=card,
            done=False,
        )

    async def resume(self, ctx: SessionContext, reply: str) -> AgentResult:
        """中断恢复: 用户确认深入分析方向"""
        events: list[StatusEvent] = []

        if "不需要" in reply:
            return AgentResult(
                state={"phase": "completed", "current_agent": None},
                reply="好的，以上是您的皮肤分析结果。如有其他问题随时问我哦~",
                events=events,
                done=True,
            )

        # 提取分析方向
        focus_area = "毛孔" if "毛孔" in reply else "色素" if "色素" in reply else "出油" if "出油" in reply else "综合"
        events.append(StatusEvent(
            seq=0, source="agent:photo_analyst",
            status="running", label=f"正在深入分析: {focus_area}问题...",
            created_at=_now(),
        ))

        # 基于已有的分析结果展开深入建议
        prev_analysis = ctx.agent_state.get("analysis", {}).get("skin_analysis", {})
        try:
            deep_prompt = f"""用户选择了「{reply}」方向。
之前的皮肤分析: {json.dumps(prev_analysis, ensure_ascii=False)}
请针对「{focus_area}」问题给出详细的成因分析和护理建议（200 字以内）。"""
            deep_reply = await llm_chat(
                model=settings.LLM_FLASH_MODEL,
                system_prompt="你是「肤小护·识肤师」。根据皮肤分析结果给出专业、温暖的护理建议。",
                user_prompt=deep_prompt,
                timeout_s=25.0,
                temperature=0.5,
                max_tokens=512,
            )
        except Exception:
            deep_reply = f"针对{focus_area}问题，建议您：1) 保持清洁；2) 选择适合的护肤产品；3) 必要时咨询皮肤科医生。"

        events.append(StatusEvent(
            seq=1, source="agent:photo_analyst",
            status="done", label="深入分析完成",
            created_at=_now(),
        ))

        return AgentResult(
            state={"phase": "completed", "current_agent": None},
            reply=deep_reply,
            events=events,
            done=True,
        )

    async def _call_vl_model(self, image_url: str, prompt: str) -> str:
        """调用 VL (Vision Language) 模型"""
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
        )

        messages = [
            {
                "role": "system",
                "content": VL_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
        ]

        response = await client.chat.completions.create(
            model=settings.LLM_VL_MODEL,
            messages=messages,
            temperature=0.3,
            max_tokens=1024,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content or "{}"


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
