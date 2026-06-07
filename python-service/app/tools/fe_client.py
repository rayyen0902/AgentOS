"""
FE (Forgetting Engine) gRPC 客户端 — fe_retrieve / fe_ingest
目标: knownot.cc:50052
超时: 5s

由于项目暂缺 .proto 文件，使用 httpx 实现 REST 兼容层，
接口签名严格对应 Step 5 文档。后续可替换为 gRPC stub。
"""
import logging
from typing import Optional

import httpx

from config import settings
from app.tools.models import FERetrieveInput, FERetrieveOutput, FEIngestInput, FEIngestOutput, MemoryItem

logger = logging.getLogger(__name__)

FE_BASE_URL = f"http://{settings.FE_GRPC_HOST}:{settings.FE_GRPC_PORT}"
FE_TIMEOUT = 5.0  # 文档规定 5s


async def fe_retrieve(input: FERetrieveInput) -> FERetrieveOutput:
    """
    调用 FE 服务读取记忆上下文。异常由上层 with_retry 处理，兜底在 registry 层。
    文档: Step 5 5.2
    - 超时: 5s
    """
    payload = {
        "query": input.query,
        "layer": input.layer,
        "n": input.n,
        "user_id": input.user_id,
        "namespace": input.namespace,
    }
    async with httpx.AsyncClient(timeout=FE_TIMEOUT) as client:
        resp = await client.post(
            f"{FE_BASE_URL}/api/v1/retrieve",
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

        raw_items = [
            MemoryItem(
                id=item.get("id", ""),
                text=item.get("text", ""),
                layer=item.get("layer", ""),
                score=item.get("score", 0.0),
                created_at=item.get("created_at", ""),
            )
            for item in data.get("items", [])
        ]

        # 格式化为可直接注入 prompt 的文本
        lines = [f"[{item.layer}] {item.text}" for item in raw_items]
        content = "\n".join(lines) if lines else "(no relevant memory)"

        return FERetrieveOutput(
            content=content,
            raw_items=raw_items,
            retrieved_count=len(raw_items),
        )


async def fe_ingest(input: FEIngestInput) -> FEIngestOutput:
    """
    调用 FE 服务写入记忆。
    文档: Step 5 5.3
    - 重试: 3次 (由调用方 with_retry 处理)
    - 兜底: 记录失败日志，不阻断主流程
    """
    payload = {
        "text": input.text,
        "role": input.role,
        "session_id": input.session_id,
        "user_id": input.user_id,
        "namespace": input.namespace,
        "importance": input.importance,
    }
    async with httpx.AsyncClient(timeout=FE_TIMEOUT) as client:
        resp = await client.post(
            f"{FE_BASE_URL}/api/v1/ingest",
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

        return FEIngestOutput(
            msg_id=data.get("msg_id", ""),
            success=data.get("success", False),
        )
