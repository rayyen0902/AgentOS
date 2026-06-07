"""
LLM 调用工具 — 指数退避重试 + 结构化 JSON 输出
严格对应 Step 6 文档的 LLM 超时和重试策略
"""
import asyncio
import json
import logging
from typing import Any

from openai import AsyncOpenAI

from config import settings

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
        )
    return _client


async def llm_chat(
    model: str,
    system_prompt: str,
    user_prompt: str,
    timeout_s: float = 30.0,
    json_mode: bool = False,
    temperature: float = 0.3,
    max_tokens: int = 2048,
) -> str:
    """
    调用 LLM，带指数退避重试（1s, 2s, 4s），第 3 次失败返回兜底回复。
    严格遵循 Step 6 6.1 章节的 LLM API 限流→指数退避重试策略。
    """
    client = get_client()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    extra: dict[str, Any] = {}
    if json_mode:
        extra["response_format"] = {"type": "json_object"}

    retry_delays = [1.0, 2.0, 4.0]  # 指数退避: 1s, 2s, 4s
    last_error = None

    for attempt in range(len(retry_delays) + 1):
        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **extra,
                ),
                timeout=timeout_s,
            )
            return response.choices[0].message.content or ""
        except asyncio.TimeoutError:
            last_error = f"LLM timeout after {timeout_s}s"
            logger.warning(f"[llm_chat] {model} timeout (attempt {attempt + 1}/{len(retry_delays) + 1})")
        except Exception as e:
            last_error = str(e)
            logger.warning(f"[llm_chat] {model} error (attempt {attempt + 1}/{len(retry_delays) + 1}): {e}")

        if attempt < len(retry_delays):
            delay = retry_delays[attempt]
            logger.info(f"[llm_chat] retrying in {delay}s...")
            await asyncio.sleep(delay)

    # 第 3 次失败 → 返回兜底回复
    logger.error(f"[llm_chat] {model} all retries exhausted: {last_error}")
    return '{"error": "llm_unavailable", "message": "AI 服务暂时不可用，请稍后再试~"}'
