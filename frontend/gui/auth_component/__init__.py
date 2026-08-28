from pathlib import Path
from typing import Literal

import streamlit.components.v1 as components

_COMPONENT_DIR = Path(__file__).parent / "frontend"

_auth_bridge = components.declare_component("auth_bridge", path=str(_COMPONENT_DIR))


def auth_bridge(
    action: Literal["login", "refresh", "logout"],
    payload: dict | None = None,
    key: str | None = None,
) -> dict | None:
    """Runs one browser-side auth call (login/refresh/logout) via a same-origin
    fetch with credentials, so the HttpOnly refresh cookie set by the backend
    reaches (and is sent by) the browser rather than the Streamlit server.

    Like any Streamlit component, this returns None on the run where the
    action is first triggered; the real result (``{"ok", "status", "body"}``)
    is only available once the browser call finishes and Streamlit reruns.
    """
    return _auth_bridge(action=action, payload=payload or {}, key=key, default=None)
