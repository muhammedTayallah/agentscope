import logging

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def check_database(session: AsyncSession) -> bool:
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Database health check failed")
        return False
    return True


async def check_redis(redis_url: str) -> bool:
    client = Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
    try:
        return bool(await client.ping())
    except Exception:
        logger.exception("Redis health check failed")
        return False
    finally:
        await client.aclose()
