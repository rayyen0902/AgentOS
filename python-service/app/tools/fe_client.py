"""
FE (Forgetting Engine) 客户端 — fe_retrieve / fe_ingest
目标: knownot.cc:50052 (gRPC 优先 + HTTP 降级)
超时: 5s

严格对齐遗忘引擎 proto 定义 (fe_service.proto)。
gRPC stub 文件: fe_service_pb2.py / fe_service_pb2_grpc.py
"""
import logging
from typing import Optional

import grpc
import httpx

from config import settings
from app.tools.models import FERetrieveInput, FERetrieveOutput, FEIngestInput, FEIngestOutput, MemoryItem
from app.tools.fe_service_pb2 import (
    RetrieveRequest,
    IngestRequest,
)
from app.tools.fe_service_pb2_grpc import ForgettingEngineStub

logger = logging.getLogger(__name__)

FE_GRPC_TARGET = f"{settings.FE_GRPC_HOST}:{settings.FE_GRPC_PORT}"
FE_HTTP_BASE = f"http://{settings.FE_GRPC_HOST}:{settings.FE_GRPC_PORT}"
FE_TIMEOUT = 5.0  # 文档规定 5s (S5-10: 已统一 float)


def _kin_id_from_input(user_id: int, namespace: str) -> Optional[str]:
    fixed = getattr(settings, "FE_KIN_ID", None) or ""
    if fixed:
        return fixed
    return None


def _grpc_channel():
    return grpc.aio.insecure_channel(FE_GRPC_TARGET)


async def fe_retrieve(input: FERetrieveInput) -> FERetrieveOutput:
    """
    调用 FE retrieve。gRPC 优先 → HTTP 降级。
    异常由上层 with_retry 处理，兜底在 registry 层。
    """
    kin_id = _kin_id_from_input(input.user_id, input.namespace)

    # --- gRPC 路径 ---
    try:
        req = RetrieveRequest(
            query=input.query,
            layer=input.layer,
            n=input.n,
            kin_id=kin_id or "",
            session_id="",
        )
        async with _grpc_channel() as channel:
            stub = ForgettingEngineStub(channel)
            resp = await stub.Retrieve(req, timeout=FE_TIMEOUT)

        raw_items = [
            MemoryItem(
                id=item.id,
                text=item.text,
                layer=item.layer,
                score=item.score,
                created_at=item.created_at,
            )
            for item in resp.items
        ]
        lines = [f"[{item.layer}] {item.text}" for item in raw_items]
        content = "\n".join(lines) if lines else "(no relevant memory)"
        return FERetrieveOutput(
            content=content,
            raw_items=raw_items,
            retrieved_count=len(raw_items),
        )
    except Exception as e:
        logger.warning(f"[fe_retrieve] gRPC failed, fallback to HTTP: {e}")

    # --- HTTP 降级路径 ---
    payload: dict = {
        "query": input.query,
        "layer": input.layer,
        "n": input.n,
    }
    if kin_id:
        payload["kin_id"] = kin_id
    else:
        payload["user_id"] = input.user_id
        payload["namespace"] = input.namespace

    async with httpx.AsyncClient(timeout=FE_TIMEOUT) as client:
        resp = await client.post(f"{FE_HTTP_BASE}/api/v1/retrieve", json=payload)
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
        lines = [f"[{item.layer}] {item.text}" for item in raw_items]
        content = "\n".join(lines) if lines else "(no relevant memory)"
        return FERetrieveOutput(
            content=content,
            raw_items=raw_items,
            retrieved_count=len(raw_items),
        )


async def fe_ingest(input: FEIngestInput) -> FEIngestOutput:
    """
    调用 FE ingest。gRPC 优先 → HTTP 降级。
    异常由上层 with_retry 处理。
    """
    kin_id = _kin_id_from_input(input.user_id, input.namespace)

    # --- gRPC 路径 ---
    try:
        req = IngestRequest(
            text=input.text,
            role=input.role,
            session_id=input.session_id,
            kin_id=kin_id or "",
            importance=input.importance,
        )
        async with _grpc_channel() as channel:
            stub = ForgettingEngineStub(channel)
            resp = await stub.Ingest(req, timeout=FE_TIMEOUT)
        return FEIngestOutput(
            msg_id=resp.msg_id,
            success=resp.success,
        )
    except Exception as e:
        logger.warning(f"[fe_ingest] gRPC failed, fallback to HTTP: {e}")

    # --- HTTP 降级路径 ---
    payload: dict = {
        "text": input.text,
        "role": input.role,
        "session_id": input.session_id,
        "importance": input.importance,
    }
    if kin_id:
        payload["kin_id"] = kin_id
    else:
        payload["user_id"] = input.user_id
        payload["namespace"] = input.namespace

    async with httpx.AsyncClient(timeout=FE_TIMEOUT) as client:
        resp = await client.post(f"{FE_HTTP_BASE}/api/v1/ingest", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return FEIngestOutput(
            msg_id=data.get("msg_id", ""),
            success=data.get("success", False),
        )
