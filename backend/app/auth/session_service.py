import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import User, UserSession


def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _as_aware_utc(value: datetime) -> datetime:
    # Some dialects (e.g. SQLite) round-trip datetimes as naive even when the
    # column is declared timezone-aware; treat a naive value as UTC.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _split_credential(credential: str) -> tuple[UUID, str]:
    try:
        session_id_str, secret = credential.split(".", 1)
        return UUID(session_id_str), secret
    except (ValueError, AttributeError) as e:
        raise HTTPException(status_code=401, detail="Invalid session credential") from e


async def create_session(user: User, session: AsyncSession, user_agent: str | None = None) -> str:
    session_id = uuid4()
    secret = secrets.token_urlsafe(48)

    user_session = UserSession(
        id=session_id,
        user_id=user.id,
        token_hash=_hash_secret(secret),
        expires_at=datetime.now(tz=UTC) + timedelta(days=settings.refresh_token_expiry_days),
        user_agent=user_agent,
    )
    session.add(user_session)
    await session.commit()

    return f"{session_id}.{secret}"


async def rotate_session(credential: str, session: AsyncSession) -> tuple[User, str]:
    session_id, secret = _split_credential(credential)

    statement = select(UserSession).where(UserSession.id == session_id).with_for_update()
    result = await session.execute(statement)
    user_session = result.scalar_one_or_none()

    if user_session is None:
        raise HTTPException(status_code=401, detail="Invalid session")

    if user_session.revoked_at is not None:
        raise HTTPException(status_code=401, detail="Session has been revoked")

    now = datetime.now(tz=UTC)
    if _as_aware_utc(user_session.expires_at) < now:
        raise HTTPException(status_code=401, detail="Session has expired")

    if not hmac.compare_digest(user_session.token_hash, _hash_secret(secret)):
        # The session id is valid but the secret doesn't match: treat this as a
        # replay of an already-rotated credential and revoke the session.
        user_session.revoked_at = now
        await session.commit()
        raise HTTPException(status_code=401, detail="Invalid session")

    user_statement = select(User).where(User.id == user_session.user_id)
    user_result = await session.execute(user_statement)
    user = user_result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid session")

    new_secret = secrets.token_urlsafe(48)
    user_session.token_hash = _hash_secret(new_secret)
    user_session.last_used_at = now
    await session.commit()

    return user, f"{session_id}.{new_secret}"


async def revoke_session(credential: str, session: AsyncSession) -> None:
    try:
        session_id, _secret = _split_credential(credential)
    except HTTPException:
        return

    statement = select(UserSession).where(UserSession.id == session_id)
    result = await session.execute(statement)
    user_session = result.scalar_one_or_none()

    if user_session is None or user_session.revoked_at is not None:
        return

    user_session.revoked_at = datetime.now(tz=UTC)
    await session.commit()


async def delete_expired_sessions(session: AsyncSession, revoked_retention_days: int = 30) -> int:
    now = datetime.now(tz=UTC)
    statement = delete(UserSession).where(
        or_(
            UserSession.expires_at < now,
            UserSession.revoked_at < now - timedelta(days=revoked_retention_days),
        )
    )
    result = await session.execute(statement)
    await session.commit()

    return result.rowcount or 0
