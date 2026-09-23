"""FastAPI entrypoint."""

from fastapi import FastAPI, Response, status
from sqlalchemy import text

from app.db import engine, redis_client

app = FastAPI(title="EPL Predictor")


async def check_postgres() -> str:
    """Return "ok" if Postgres answers `SELECT 1`, else the error message."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:  # any failure means "unhealthy", report why
        return f"error: {exc}"


async def check_redis() -> str:
    """Return "ok" if Redis answers PING, else the error message."""
    try:
        await redis_client.ping()
        return "ok"
    except Exception as exc:
        return f"error: {exc}"


@app.get("/health")
async def health(response: Response) -> dict[str, str]:
    """Report whether the API can reach Postgres and Redis. 503 if either is down."""
    checks = {"postgres": await check_postgres(), "redis": await check_redis()}
    healthy = all(v == "ok" for v in checks.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if healthy else "degraded", **checks}
