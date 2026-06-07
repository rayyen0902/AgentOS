import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from config import settings, Settings
from redis_util import redis_client
from db_util import db
from app.api.routes import router as agent_router

logger = logging.getLogger(__name__)


# ============================================================
# Step 8: Cron 定时任务调度器
# ============================================================

async def cron_scheduler_loop() -> None:
    """
    Step 8 定时任务调度器:
    - Agent Journal: 每周日 00:00 UTC 触发
    - Observation 告警: 每 5 分钟检查一次
    - Agent 评价: 每 7 天运行一次
    """
    last_journal_week = -1
    last_evaluation_day = -1

    while True:
        try:
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc)

            # ---- Observation 告警（每 5 分钟） ----
            try:
                from app.observation.alert_rules import run_alert_check
                await run_alert_check()
            except Exception as e:
                logger.error(f"[cron] alert check failed: {e}")

            # ---- Agent Journal（每周日 00:00 UTC） ----
            # weekday(): Monday=0, Sunday=6
            if now.weekday() == 6 and now.hour == 0 and now.minute < 5:
                current_week = now.isocalendar()[1]
                if current_week != last_journal_week:
                    last_journal_week = current_week
                    try:
                        from app.agents.journal import run_weekly_journal
                        asyncio.create_task(run_weekly_journal())
                    except Exception as e:
                        logger.error(f"[cron] weekly journal failed: {e}")

            # ---- Agent 评价（每 7 天） ----
            if now.day != last_evaluation_day:
                # 每个周日运行
                if now.weekday() == 6:
                    last_evaluation_day = now.day
                    try:
                        from app.agents.evaluation import run_evaluation
                        asyncio.create_task(run_evaluation())
                    except Exception as e:
                        logger.error(f"[cron] evaluation failed: {e}")

            await asyncio.sleep(300)  # 每 5 分钟检查一次

        except asyncio.CancelledError:
            logger.info("[cron] scheduler cancelled")
            break
        except Exception as e:
            logger.error(f"[cron] scheduler loop error: {e}")
            await asyncio.sleep(60)


_cron_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _cron_task

    # startup
    errors = Settings.validate()
    if errors:
        raise RuntimeError(f"Config validation errors: {'; '.join(errors)}")

    await redis_client.connect()
    pong = await redis_client._client.ping()
    assert pong, "Redis PING failed"

    await db.connect()
    db_ok = await db.is_available()
    assert db_ok, "Database check failed"

    print(f"[OK] Python service starting on :{settings.PORT} [{settings.ENV}]")
    print(f"[OK] Redis connected, PING=PONG")
    print(f"[OK] Database connected")
    print(f"[OK] Config loaded: LLM={settings.LLM_PRO_MODEL}/{settings.LLM_FLASH_MODEL}, EMB={settings.EMBEDDING_MODEL}")

    # Step 8: 启动 Cron 定时任务
    _cron_task = asyncio.create_task(cron_scheduler_loop())
    print(f"[OK] Step 8 Cron scheduler started (Journal + Alerts + Evaluation)")

    yield

    # shutdown
    if _cron_task:
        _cron_task.cancel()
        try:
            await _cron_task
        except asyncio.CancelledError:
            pass
    await db.disconnect()
    await redis_client.disconnect()


app = FastAPI(
    title="AgentOS Python Service",
    version="0.3.0",
    lifespan=lifespan,
)

app.include_router(agent_router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "code": 5001,
            "message": str(exc),
            "data": None,
            "trace_id": "",
        },
    )


@app.get("/health")
async def health():
    redis_ok = await redis_client.is_available()
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "status": "ok" if redis_ok else "degraded",
            "redis": "connected" if redis_ok else "unavailable",
        },
        "trace_id": "",
    }
