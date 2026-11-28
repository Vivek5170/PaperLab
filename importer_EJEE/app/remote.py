"""Client for a PaperLab server's archivist bundle API, and a Meta key probe.

Uses only the standard library. Never follows redirects (a redirect could
replay the password or bundle elsewhere), never logs secrets, and maps every
failure to a ``RemoteError`` with a ``kind`` the queue uses to decide
between "pause and fix settings" and "this part failed".

kinds: ``network`` (unreachable / DNS / TLS / timeout), ``auth`` (wrong
password), ``server`` (setup problem on the server: HTTPS required, default
password, archive missing), ``busy`` (429/503, retry later), ``conflict``
(409), ``invalid`` (413/415/422, the bundle itself), ``meta`` (key rejected).
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

LOOPBACK = {"localhost", "127.0.0.1", "::1"}


class RemoteError(Exception):
    def __init__(self, kind, message, status=None):
        super().__init__(message)
        self.kind, self.status = kind, status


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RemoteError("server", f"The server redirected to {newurl}. Use that address as the server link.", code)


def normalize_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise RemoteError("server", "The server link must start with https:// (or http:// for this computer only).")
    if parts.scheme == "http" and parts.hostname not in LOOPBACK:
        raise RemoteError("server", "PaperLab only accepts bundle uploads over HTTPS. Use an https:// link "
                                    "(http:// works only for a server on this computer).")
    if parts.query or parts.fragment:
        raise RemoteError("server", "The server link must not contain ? or #.")
    return url


def _detail(body: bytes) -> str:
    try:
        data = json.loads(body.decode("utf-8"))
        detail = data.get("detail") if isinstance(data, dict) else None
        if isinstance(detail, list):
            detail = "; ".join(str(d.get("msg", d)) for d in detail)
        return str(detail or data)[:500]
    except (ValueError, UnicodeDecodeError, AttributeError):
        return body[:300].decode("utf-8", "replace")


class PaperLab:
    def __init__(self, base_url: str, password: str, timeout: float = 600):
        self.base = normalize_url(base_url)
        self.password = password
        self.timeout = timeout
        self.cookie = None
        self.opener = urllib.request.build_opener(
            _NoRedirect, urllib.request.HTTPSHandler(context=ssl.create_default_context()))

    def _call(self, method, path, *, body=None, headers=None, params=None, timeout=None):
        url = self.base + path + (("?" + urllib.parse.urlencode(params)) if params else "")
        req = urllib.request.Request(url, data=body, method=method, headers=dict(headers or {}))
        req.add_header("Accept", "application/json")
        if self.cookie:
            req.add_header("Cookie", self.cookie)
        try:
            with self.opener.open(req, timeout=timeout or self.timeout) as resp:
                return resp.status, resp.read(), resp.headers
        except RemoteError:
            raise
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), exc.headers
        except ssl.SSLError as exc:
            raise RemoteError("network", f"TLS/certificate problem talking to {self.base}: {exc.reason or exc}")
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise RemoteError("network", f"Cannot reach {self.base}: {reason}")
        except (TimeoutError, OSError) as exc:
            raise RemoteError("network", f"Cannot reach {self.base}: {exc}")

    def health(self):
        status, body, _ = self._call("GET", "/api/health", timeout=20)
        if status != 200:
            raise RemoteError("server", f"{self.base} answered {status} on /api/health; is this a PaperLab server?",
                              status)
        try:
            ok = json.loads(body).get("ok")
        except (ValueError, AttributeError):
            ok = False
        if not ok:
            raise RemoteError("server", f"{self.base} is not a PaperLab server (unexpected /api/health reply).")

    def login(self):
        status, body, headers = self._call(
            "POST", "/api/auth/login", body=json.dumps({"password": self.password}).encode(),
            headers={"Content-Type": "application/json"}, timeout=30)
        if status == 401:
            raise RemoteError("auth", "The archivist password was rejected by the PaperLab server.", 401)
        if status not in (200, 204):
            raise RemoteError("server", f"Login failed ({status}): {_detail(body)}", status)
        cookie = headers.get("Set-Cookie", "")
        self.cookie = cookie.split(";", 1)[0] if "=" in cookie else None
        if not self.cookie:
            raise RemoteError("server", "The server did not start a session (no cookie returned).")

    def logout(self):
        if self.cookie:
            try:
                self._call("POST", "/api/auth/logout", timeout=15)
            except RemoteError:
                pass
            self.cookie = None

    def import_bundle(self, path, dry_run: bool, allow_untagged: bool = True) -> tuple[int, dict]:
        path = Path(path)
        size = path.stat().st_size
        params = {"dry_run": "true" if dry_run else "false"}
        if allow_untagged:
            params["allow_untagged"] = "true"  # untagged questions go to PaperLab's Tagging Inbox
        with path.open("rb") as fh:
            status, body, headers = self._call(
                "POST", "/api/bundles/import", body=fh, params=params,
                headers={"Content-Type": "application/octet-stream", "Content-Length": str(size)})
        if status in (200, 201):
            return status, json.loads(body)
        message = _detail(body)
        if status in (401,):
            raise RemoteError("auth", "The server session was refused; check the archivist password.", status)
        if status == 403:
            raise RemoteError("server", f"The server refused the upload: {message}", status)
        if status in (408, 429, 503):
            setup = status == 503 and ("password" in message.lower() or "initialized" in message.lower())
            kind = "server" if setup else "busy"
            raise RemoteError(kind, f"Server busy or not ready ({status}): {message}", status)
        if status == 409:
            raise RemoteError("conflict", message, status)
        if status in (400, 413, 415, 422):
            raise RemoteError("invalid", f"The server rejected the bundle ({status}): {message}", status)
        raise RemoteError("server", f"Unexpected server reply {status}: {message}", status)


def check_server(url, password) -> dict:
    """Free check: reachable, is PaperLab, password accepted. Logs out again."""
    client = PaperLab(url, password, timeout=30)
    client.health()
    client.login()
    client.logout()
    return {"ok": True, "url": client.base}


def publish(url, password, bundle) -> dict:
    """Preview, then publish. Same bytes on retry, so a lost reply is safe:
    the server returns the original receipt with ``already_imported``."""
    client = PaperLab(url, password)
    client.health()
    client.login()
    send = client.import_bundle

    def patient(path, dry_run):
        # The server takes one import at a time; parallel workers queue up
        # here instead of pausing everything on a 429/503 "busy".
        import time
        for attempt in range(30):
            try:
                return send(path, dry_run=dry_run)
            except RemoteError as exc:
                if exc.kind != "busy" or attempt == 29:
                    raise
                time.sleep(5 + 2 * attempt)

    client.import_bundle = patient
    try:
        try:
            _status, preview = client.import_bundle(bundle, dry_run=True)
        except RemoteError as exc:
            # A 409 preview can mean *this* bundle was already published by an
            # earlier attempt whose reply was lost; publishing the same bytes
            # then returns the original receipt instead of a second copy.
            if exc.kind != "conflict":
                raise
            preview = None
        status, receipt = client.import_bundle(bundle, dry_run=False)
        receipt["preview"] = preview
        receipt["http_status"] = status
        return receipt
    finally:
        client.logout()


def check_meta_key(key, base_url) -> dict:
    """Free probe of the model endpoint's /models listing.

    401/403 means the key is rejected. Any other reply (including an
    endpoint without /models) cannot prove the key either way; the first
    model call will, and the queue pauses safely if it fails.
    """
    if not key:
        raise RemoteError("meta", "No Meta API key is set.")
    url = base_url.rstrip("/") + "/models"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=20) as resp:
            return {"ok": True, "verified": True, "status": resp.status}
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise RemoteError("meta", f"The Meta API key was rejected ({exc.code}).", exc.code)
        return {"ok": True, "verified": False, "status": exc.code,
                "note": "The endpoint did not confirm the key; it will be checked on the first model call."}
    except RemoteError:
        return {"ok": True, "verified": False, "note": "Could not confirm the key (redirect)."}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RemoteError("network", f"Cannot reach the model endpoint {base_url}: {getattr(exc, 'reason', exc)}")
