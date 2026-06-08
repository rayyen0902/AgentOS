import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from config import settings, Settings
from redis_util import redis_client
from app.api.routes import router as agent_router

logger = logging.getLogger(__name__)


# ============================================================
# Step 8: Cron 定时任务调度器
# ============================================================

async def cron_scheduler_loop() -> None:
    """
    Step 8 定时任务调度器（asyncio 内置实现，无需外部 crontab 依赖）。
    S8-16: 实现方式 — asyncio loop 内每 5 分钟轮询检查时间条件。

    定时任务:
    - Agent Journal: 每周日 00:00 UTC 触发
    - Observation 告警: 每 5 分钟检查一次
    - Agent 评价: 每周日（与 Journal 同频）触发
    """
    last_journal_week = -1
    # S8-15: 用 ISO week string (YYYY-Www) 代替 now.day 避免跨月溢出
    last_evaluation_date: str = ""

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
            if now.weekday() == 6 and now.hour == 0 and now.minute < 5:
                current_week = now.isocalendar()[1]
                if current_week != last_journal_week:
                    last_journal_week = current_week
                    try:
                        from app.agents.journal import run_weekly_journal
                        asyncio.create_task(run_weekly_journal())
                    except Exception as e:
                        logger.error(f"[cron] weekly journal failed: {e}")

            # ---- Agent 评价（每周日，与 Journal 同频） ----
            # S8-15 修复: 用 YYYY-Www 比较避免 now.day 跨月脆弱性
            if now.weekday() == 6:
                current_date_key = now.strftime("%Y-W%W")
                if current_date_key != last_evaluation_date:
                    last_evaluation_date = current_date_key
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

    # S2-07: Redis 降级启动 — 不可用时仅 warn，不崩溃
    redis_ok = False
    try:
        await redis_client.connect()
        # S2-06: 用公共 API is_available() 而非 _client.ping()
        redis_ok = await redis_client.is_available()
        if redis_ok:
            print(f"[OK] Redis connected")
        else:
            print(f"[WARN] Redis connected but ping failed — degraded mode")
    except Exception as e:
        logger.warning(f"[startup] Redis unavailable ({e}) — degraded mode, using PG fallback")

    # S2-07: PG 降级启动 — 不可用时仅 warn，不崩溃
    pg_ok = False
    try:
        from db_util import db
        await db.connect()
        pg_ok = await db.is_available()
        if pg_ok:
            print(f"[OK] Database connected")
        else:
            print(f"[WARN] Database connected but not available — degraded mode")
    except Exception as e:
        logger.warning(f"[startup] Database unavailable ({e}) — degraded mode")

    # S2-07: 全不可用才崩溃
    if not redis_ok and not pg_ok:
        raise RuntimeError("Both Redis and PostgreSQL unavailable — cannot start")

    print(f"[OK] Python service starting on :{settings.PORT} [{settings.ENV}]")
    print(f"[OK] Config loaded: LLM={settings.LLM_PRO_MODEL}/{settings.LLM_FLASH_MODEL}, EMB={settings.EMBEDDING_MODEL}")
    if not redis_ok:
        print(f"[INFO] Running in PG-only degraded mode (no Redis)")
    if not pg_ok:
        print(f"[INFO] Running in Redis-only degraded mode (no PG)")

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

    try:
        from db_util import db
        await db.disconnect()
    except Exception:
        pass
    await redis_client.disconnect()


app = FastAPI(
    title="AgentOS Python Service",
    version="0.3.0",
    lifespan=lifespan,
)

app.include_router(agent_router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # S2-04: 全局异常也遵循统一格式 {code, message, data, trace_id}
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
    """主 health 端点 — 综合 Redis + PG 状态"""
    redis_ok = await redis_client.is_available()

    pg_ok = True
    try:
        from db_util import db
        pg_ok = await db.is_available()
    except Exception:
        pg_ok = False

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "status": "ok" if (redis_ok and pg_ok) else "degraded",
            "redis": "connected" if redis_ok else "unavailable",
            "postgres": "connected" if pg_ok else "unavailable",
        },
        "trace_id": "",
    }
