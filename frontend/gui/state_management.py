import base64
import json
import time
from enum import StrEnum
from uuid import UUID

import api_utils
import streamlit as st
from auth_component import auth_bridge
from config import settings

MODEL_NAMES = settings.model_names or ["llama3.2:1b"]

# Refresh the access token this many seconds before it actually expires, to
# leave enough margin for the browser round trip to finish first.
TOKEN_REFRESH_MARGIN_SECONDS = 60


class Page(StrEnum):
    HOME = "home"
    LOGIN = "login"
    REGISTER = "register"


class User:
    def __init__(
        self,
        is_authenticated: bool = False,
        username: str | None = None,
        access_token: str | None = None,
        threads: list[dict] | None = None,
    ):
        self.is_authenticated = is_authenticated
        self.username = username
        self.access_token = access_token
        self.threads = threads or []


class Thread:
    def __init__(
        self,
        id: UUID | None = None,
        title: str = "",
        user_id: UUID | None = None,
        messages: list | None = None,
        documents: list | None = None,
    ):
        self.id = id
        self.user_id = user_id
        self.title = title
        self.messages = messages or []
        self.documents = documents or []


def initialize_state() -> None:
    if "page" not in st.session_state:
        st.session_state["page"] = Page.HOME

    if "user" not in st.session_state:
        st.session_state["user"] = User()

    if "thread" not in st.session_state:
        st.session_state["thread"] = Thread()

    if "model_name" not in st.session_state:
        st.session_state["model_name"] = MODEL_NAMES[0]


def new_chat():
    st.session_state["thread"] = Thread()


def update_thread(thread_id: UUID, title: str):
    updated_thread_response = api_utils.update_thread(thread_id, title)
    user_id = updated_thread_response.get("user_id")
    st.session_state["thread"].id = thread_id
    st.session_state["thread"].title = title
    st.session_state["thread"].user_id = user_id


def change_thread(thread_id: UUID) -> None:
    get_thread_response = api_utils.get_thread(thread_id)
    title = get_thread_response.get("title")
    user_id = get_thread_response.get("user_id")

    st.session_state["thread"] = Thread(id=thread_id, title=title, user_id=user_id)  # type: ignore
    update_document_list(thread_id)
    update_chat_history(thread_id)


def update_document_list(thread_id: UUID) -> None:
    documents = []
    documents_response = api_utils.list_document(thread_id)
    if documents_response is None:
        st.sidebar.error("Failed to retrieve document list. Please try again.")
    else:
        documents = documents_response

    st.session_state["thread"].documents = documents


def update_user_threads() -> list[dict]:
    threads = api_utils.get_user_threads()
    st.session_state["user"].threads = threads
    return threads


def update_chat_history(thread_id: UUID) -> None:
    chat_messages = []
    chat_history_response = api_utils.get_chat_history(thread_id)
    if isinstance(chat_history_response, list):
        chat_messages = chat_history_response
    else:
        st.sidebar.error(chat_history_response.get("details", "Failed to retrieve chat history. Please try again."))

    st.session_state["thread"].messages = chat_messages


def authenticate_user(auth_response: dict) -> None:
    """Used for login and initial-session restore, where there is no existing
    thread selection worth preserving yet."""
    st.session_state["user"] = User(
        is_authenticated=True,
        username=auth_response.get("user", {}).get("username"),
        access_token=auth_response.get("access_token"),
    )
    update_user_threads()
    st.session_state["thread"] = Thread()


def _update_access_token(auth_response: dict) -> None:
    """Used for routine mid-session token refresh: updates only the access
    token, leaving the currently open thread/messages untouched."""
    user: User = st.session_state["user"]
    user.access_token = auth_response.get("access_token")
    if username := auth_response.get("user", {}).get("username"):
        user.username = username


def logout_user() -> None:
    st.session_state["page"] = Page.HOME
    st.session_state["user"] = User()
    st.session_state["thread"] = Thread()
    st.session_state["model_name"] = MODEL_NAMES[0]


def _decode_jwt_exp(token: str) -> int | None:
    """Reads the `exp` claim out of a JWT without verifying it - only used
    locally to decide whether it's worth proactively refreshing; the backend
    is always the one that actually verifies the token."""
    try:
        payload_b64 = token.split(".")[1]
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        return payload.get("exp")
    except Exception:
        return None


def restore_authentication() -> None:
    """Called once per fresh Streamlit session, before anything else renders.
    Tries to exchange the browser's HttpOnly refresh cookie (if any) for a new
    access token, so a page reload/reopen restores the signed-in user."""
    if st.session_state.get("auth_restore_attempted"):
        return

    result = auth_bridge(action="refresh", key="restore_auth")
    if result is None:
        # First trigger this session: the browser fetch is in flight. Stop
        # rendering so nothing (sidebar, pages) flashes an anonymous state
        # before we know the real one; the component's response reruns us.
        st.stop()

    st.session_state["auth_restore_attempted"] = True
    if result.get("ok"):
        authenticate_user(result.get("body") or {})
        st.rerun()


def ensure_fresh_token() -> None:
    """Proactively refreshes the access token when it's missing or close to
    expiring, before any authenticated API calls are made this run. This is
    what stands in for a per-call 401-retry: Streamlit components can't do a
    synchronous retry inside a single function, but every user interaction is
    already a full script rerun, so checking expiry at the top of each run
    achieves the same outcome (and covers the streaming-chat case, since the
    chat UI renders after this check)."""
    user: User = st.session_state["user"]
    if not user.is_authenticated:
        return

    exp = _decode_jwt_exp(user.access_token) if user.access_token else None
    if exp is not None and exp - time.time() > TOKEN_REFRESH_MARGIN_SECONDS:
        return

    seq = st.session_state.get("token_refresh_seq", 0)
    result = auth_bridge(action="refresh", key=f"token_refresh_{seq}")
    if result is None:
        st.stop()

    st.session_state["token_refresh_seq"] = seq + 1
    if result.get("ok"):
        _update_access_token(result.get("body") or {})
    else:
        # The refresh cookie is gone/expired/revoked: the session has ended.
        logout_user()
        st.rerun()
