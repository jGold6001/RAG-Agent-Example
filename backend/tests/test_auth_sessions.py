"""Tests for the cookie-backed refresh session flow (docs/persistent-auth-session.md §13).

Note: a concurrency test for "two simultaneous refresh attempts cannot both
succeed" is intentionally omitted. `rotate_session` relies on `SELECT ... FOR
UPDATE` to serialize concurrent rotations, but SQLite (used here for a fast,
dependency-free test DB) does not implement real row locking, so a
concurrency test against it wouldn't actually exercise that guarantee.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import User, UserSession

COOKIE_NAME = settings.auth_cookie_name


async def _login(client: AsyncClient) -> tuple[dict, str]:
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": "test@example.com", "password": "correcthorse123"},
    )
    assert response.status_code == 200
    body = response.json()
    credential = response.cookies[COOKIE_NAME]
    return body, credential


@pytest.mark.usefixtures("test_user")
class TestLogin:
    async def test_login_sets_cookie_and_creates_one_session(self, client: AsyncClient, db_session: AsyncSession):
        response = await client.post(
            "/api/v1/auth/login",
            data={"username": "test@example.com", "password": "correcthorse123"},
        )
        assert response.status_code == 200
        assert "refresh_token" not in response.json()

        set_cookie_header = response.headers["set-cookie"]
        assert COOKIE_NAME in set_cookie_header
        assert "HttpOnly" in set_cookie_header
        assert "samesite=lax" in set_cookie_header.lower()

        result = await db_session.execute(select(UserSession))
        assert len(result.scalars().all()) == 1

    async def test_stored_hash_is_not_the_raw_credential(self, client: AsyncClient, db_session: AsyncSession):
        _body, credential = await _login(client)
        _session_id, secret = credential.split(".", 1)

        result = await db_session.execute(select(UserSession))
        user_session = result.scalar_one()

        assert user_session.token_hash != secret
        assert user_session.token_hash != credential
        assert len(user_session.token_hash) == 64


@pytest.mark.usefixtures("test_user")
class TestRefresh:
    async def test_refresh_rotates_credential_and_returns_new_access_token(self, client: AsyncClient):
        login_body, old_credential = await _login(client)

        response = await client.post("/api/v1/auth/refresh", cookies={COOKIE_NAME: old_credential})
        assert response.status_code == 200
        assert response.json()["access_token"] != login_body["access_token"]

        new_credential = response.cookies[COOKIE_NAME]
        assert new_credential != old_credential
        assert new_credential.split(".", 1)[0] == old_credential.split(".", 1)[0]

    async def test_reusing_rotated_credential_is_rejected_and_revokes_session(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _body, old_credential = await _login(client)
        await client.post("/api/v1/auth/refresh", cookies={COOKIE_NAME: old_credential})

        replay_response = await client.post("/api/v1/auth/refresh", cookies={COOKIE_NAME: old_credential})
        assert replay_response.status_code == 401

        session_id, _secret = old_credential.split(".", 1)
        result = await db_session.execute(select(UserSession).where(UserSession.id == UUID(session_id)))
        user_session = result.scalar_one()
        assert user_session.revoked_at is not None

    async def test_missing_cookie_is_rejected(self, client: AsyncClient):
        response = await client.post("/api/v1/auth/refresh")
        assert response.status_code == 401

    async def test_expired_session_is_rejected(self, client: AsyncClient, db_session: AsyncSession):
        _body, credential = await _login(client)
        session_id, _secret = credential.split(".", 1)

        result = await db_session.execute(select(UserSession).where(UserSession.id == UUID(session_id)))
        user_session = result.scalar_one()
        user_session.expires_at = datetime.now(tz=UTC) - timedelta(days=1)
        await db_session.commit()

        response = await client.post("/api/v1/auth/refresh", cookies={COOKIE_NAME: credential})
        assert response.status_code == 401

    async def test_revoked_session_is_rejected(self, client: AsyncClient, db_session: AsyncSession):
        _body, credential = await _login(client)
        session_id, _secret = credential.split(".", 1)

        result = await db_session.execute(select(UserSession).where(UserSession.id == UUID(session_id)))
        user_session = result.scalar_one()
        user_session.revoked_at = datetime.now(tz=UTC)
        await db_session.commit()

        response = await client.post("/api/v1/auth/refresh", cookies={COOKIE_NAME: credential})
        assert response.status_code == 401

    async def test_deactivated_user_cannot_refresh(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ):
        _body, credential = await _login(client)

        test_user.is_active = False
        db_session.add(test_user)
        await db_session.commit()

        response = await client.post("/api/v1/auth/refresh", cookies={COOKIE_NAME: credential})
        assert response.status_code == 401


@pytest.mark.usefixtures("test_user")
class TestLogout:
    async def test_logout_revokes_session_and_clears_cookie(self, client: AsyncClient, db_session: AsyncSession):
        _body, credential = await _login(client)

        response = await client.post("/api/v1/auth/logout", cookies={COOKIE_NAME: credential})
        assert response.status_code == 200
        assert response.cookies.get(COOKIE_NAME) in (None, "")

        session_id, _secret = credential.split(".", 1)
        result = await db_session.execute(select(UserSession).where(UserSession.id == UUID(session_id)))
        user_session = result.scalar_one()
        assert user_session.revoked_at is not None

    async def test_logout_without_cookie_still_succeeds(self, client: AsyncClient):
        response = await client.post("/api/v1/auth/logout")
        assert response.status_code == 200
