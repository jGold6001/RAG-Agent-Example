from fastapi import Response

from app.config import settings


def set_refresh_cookie(response: Response, credential: str) -> None:
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=credential,
        max_age=settings.refresh_token_expiry_days * 86400,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path="/",
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.auth_cookie_name,
        path="/",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite=settings.auth_cookie_samesite,
    )
