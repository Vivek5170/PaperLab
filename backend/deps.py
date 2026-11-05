"""Session auth reusing the Streamlit password gate (app/auth.py)."""
from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status

from app.auth import SESSION_KEY, check_password  # noqa: F401  (single source of truth)

COOKIE_NAME = "pl_session"
_sessions: set[str] = set()


def create_session() -> str:
    token = secrets.token_urlsafe(32)
    _sessions.add(token)
    return token


def destroy_session(token: str | None) -> None:
    if token:
        _sessions.discard(token)


def is_authed(session: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None) -> bool:
    return bool(session) and session in _sessions


def verify_password(candidate: str | None) -> bool:
    return check_password(candidate)


def require_admin(ok: Annotated[bool, Depends(is_authed)]) -> bool:
    if not ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "archivist login required")
    return True
