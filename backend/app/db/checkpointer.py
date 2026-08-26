from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from loguru import logger
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import settings

pool: AsyncConnectionPool | None = None
checkpointer: AsyncPostgresSaver | None = None


async def create_connection() -> AsyncConnectionPool:
    global pool

    if pool is not None:
        return pool

    logger.info("Creating checkpointer connection pool...")
    connection_kwargs = {"autocommit": True, "row_factory": dict_row}
    pool = AsyncConnectionPool(conninfo=settings.checkpointer_uri, kwargs=connection_kwargs, open=False)
    await pool.open()
    logger.info("✅ Checkpointer connection pool created successfully")
    return pool


async def get_checkpointer() -> AsyncPostgresSaver:
    global checkpointer

    if checkpointer is not None:
        return checkpointer

    conn_pool = await create_connection()
    checkpointer = AsyncPostgresSaver(conn=conn_pool)  # type: ignore
    await checkpointer.setup()
    logger.info("✅ PostgresCheckpointer initialized successfully")
    return checkpointer


async def close_connection() -> None:
    global pool

    if pool is not None:
        logger.info("Closing checkpointer connection pool...")
        await pool.close()
        logger.info("✅ Checkpointer connection pool closed successfully")
        pool = None
