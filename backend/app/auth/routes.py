from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status

from app.config import settings
from app.db.main import SessionDep
from app.users import service as user_service
from app.users.schemas import UserCreate

from . import session_service
from .cookies import clear_refresh_cookie, set_refresh_cookie
from .dependencies import OAuth2PasswordRequestFormDep
from .schemas import LoginResponse, LogoutResponse, RefreshResponse, SignupResponse
from .utils import create_jwt_token, verify_password

auth_router = APIRouter()


@auth_router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
async def create_user_Account(user_data: UserCreate, session: SessionDep):
    new_user = await user_service.create_user(user_data, session)

    return {"message": "Account Created!", "user": new_user}


@auth_router.post("/login", response_model=LoginResponse)
async def login_users(
    form_data: OAuth2PasswordRequestFormDep, request: Request, response: Response, session: SessionDep
):
    email = form_data.username
    password = form_data.password

    user = await user_service.get_user_by_email(email, session)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Your account is not active")

    if not user.is_verified:
        raise HTTPException(status_code=403, detail="Your account is not verified")

    is_password_valid = verify_password(password, user.password_hash)
    if not is_password_valid:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access_token = create_jwt_token(
        user_data={"email": user.email, "id": str(user.id)},
        refresh=False,
    )

    credential = await session_service.create_session(user, session, user_agent=request.headers.get("user-agent"))
    set_refresh_cookie(response, credential)

    return {
        "message": "Login successful",
        "access_token": access_token,
        "user": {"email": user.email, "id": str(user.id), "username": user.username},
    }


@auth_router.post("/refresh", response_model=RefreshResponse)
async def refresh_access_token(
    response: Response,
    session: SessionDep,
    refresh_credential: str | None = Cookie(default=None, alias=settings.auth_cookie_name),
):
    if refresh_credential is None:
        raise HTTPException(status_code=401, detail="Missing session")

    user, new_credential = await session_service.rotate_session(refresh_credential, session)
    set_refresh_cookie(response, new_credential)

    access_token = create_jwt_token(
        user_data={"email": user.email, "id": str(user.id)},
        refresh=False,
    )

    return {
        "access_token": access_token,
        "user": {"email": user.email, "id": str(user.id), "username": user.username},
    }


@auth_router.post("/logout", response_model=LogoutResponse)
async def logout_user(
    response: Response,
    session: SessionDep,
    refresh_credential: str | None = Cookie(default=None, alias=settings.auth_cookie_name),
):
    if refresh_credential is not None:
        await session_service.revoke_session(refresh_credential, session)

    clear_refresh_cookie(response)

    return {"message": "Logged out successfully"}
