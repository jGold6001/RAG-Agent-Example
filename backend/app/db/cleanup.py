"""Maintenance command: delete expired/long-revoked auth sessions.

Run periodically (cron, systemd timer, etc.) outside the request path:

    python -m app.db.cleanup
"""

import asyncio

from loguru import logger

from app.auth.session_service import delete_expired_sessions
from app.db.main import async_session


async def main() -> None:
    async with async_session() as session:
        deleted = await delete_expired_sessions(session)
        logger.info(f"Deleted {deleted} expired/stale auth session(s)")


if __name__ == "__main__":
    asyncio.run(main())
