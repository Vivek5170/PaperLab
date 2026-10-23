"""Admin gate: password check + session flag (no Streamlit calls here).

The password comes from the ``PAPERLAB_ADMIN_PASSWORD`` environment
variable (set it in ``.env`` -- see ``.env.example``). If unset, a well-known
default applies and :func:`uses_default_password` reports True so the UI can
nag about it. Session state itself (``st.session_state["_admin"]``) is owned
by ``app.py``; this module stays headless-testable.
"""
from __future__ import annotations

import hmac
import os

DEFAULT_PASSWORD = "admin"
SESSION_KEY = "_admin"


def _configured_password() -> str:
    return os.environ.get("PAPERLAB_ADMIN_PASSWORD", "") or DEFAULT_PASSWORD


def uses_default_password() -> bool:
    """True when no real password is configured (change it before hosting)."""
    return not os.environ.get("PAPERLAB_ADMIN_PASSWORD")


def check_password(candidate: str | None) -> bool:
    """Timing-safe password comparison; empty/None never matches."""
    if not candidate:
        return False
    return hmac.compare_digest(candidate, _configured_password())
