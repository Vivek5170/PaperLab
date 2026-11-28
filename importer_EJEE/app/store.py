"""Local state of the EJEE Importer app: settings, secrets, cart and jobs.

Everything lives in one private data folder (default ``importer_EJEE/app/data``,
override with ``EJEE_APP_DATA``), outside Git:

* ``state.db``      settings (non-secret), cart, jobs
* ``secrets.json``  Meta API key and archivist password, owner-only permissions

Secrets are never returned to the browser; the API only reports whether
they are set plus the last four characters.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

APP = Path(__file__).resolve().parent
ROOT = APP.parent  # importer_EJEE/

STAGES = ["prepare", "extract", "figures", "pack", "classify", "verify", "export", "upload"]
PAID_STAGES = {"extract", "classify"}
SETTING_KEYS = ("server_url", "ejee_db", "uploads")
SECRET_KEYS = ("meta_api_key", "archivist_password", "extra_meta_keys")

_lock = threading.RLock()


def data_dir() -> Path:
    path = Path(os.environ.get("EJEE_APP_DATA") or APP / "data").resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def runs_rel() -> str:
    """Run root relative to importer_EJEE (shared with run_book.py)."""
    return os.environ.get("EJEE_APP_RUNS", "runs/books").strip("/\\")


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@contextmanager
def connect():
    with _lock:
        conn = sqlite3.connect(data_dir() / "state.db", timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            _schema(conn)
            yield conn
            conn.commit()
        finally:
            conn.close()


def _schema(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS cart (
        slug TEXT NOT NULL, source TEXT NOT NULL, part INTEGER NOT NULL,
        questions INTEGER NOT NULL, added_at TEXT NOT NULL,
        PRIMARY KEY (slug, part));
    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slug TEXT NOT NULL, source TEXT NOT NULL, part INTEGER NOT NULL,
        questions INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'queued',
        stage TEXT, done TEXT NOT NULL DEFAULT '[]',
        error TEXT, error_kind TEXT, detail TEXT,
        attempts INTEGER NOT NULL DEFAULT 0,
        usd REAL NOT NULL DEFAULT 0,
        bundle TEXT, bundle_sha TEXT, receipt TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE (slug, part));
    CREATE TABLE IF NOT EXISTS queue (id INTEGER PRIMARY KEY CHECK (id = 1),
        paused INTEGER NOT NULL DEFAULT 1, reason TEXT, kind TEXT);
    INSERT OR IGNORE INTO queue (id, paused) VALUES (1, 1);
    """)


# ------------------------------------------------------------------ settings
def _default_paths():
    """Defaults from importer_EJEE/books.json, only if those files exist."""
    try:
        cfg = json.loads((ROOT / "books.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    out = {}
    for key, name in (("source_db", "ejee_db"), ("asset_root", "uploads")):
        if cfg.get(key):
            path = (ROOT / cfg[key]).resolve()
            if path.exists():
                out[name] = str(path)
    return out


def settings() -> dict:
    with connect() as c:
        stored = {r["key"]: r["value"] for r in c.execute("SELECT key, value FROM settings")}
    out = {k: "" for k in SETTING_KEYS}
    out.update(_default_paths())
    out.update({k: v for k, v in stored.items() if k in SETTING_KEYS and v is not None})
    return out


def save_settings(values: dict) -> dict:
    with connect() as c:
        for key in SETTING_KEYS:
            if key in values and values[key] is not None:
                value = values[key]
                c.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                          "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value).strip()))
    return settings()


def _secrets_path() -> Path:
    return data_dir() / "secrets.json"


def secrets() -> dict:
    try:
        data = json.loads(_secrets_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    out = {k: data.get(k) or "" for k in SECRET_KEYS}
    extra = data.get("extra_meta_keys") or []
    out["extra_meta_keys"] = [k for k in extra if isinstance(k, str) and k.strip()]
    return out


def meta_keys() -> list[str]:
    """Primary key first, then extra keys (one parallel worker per key)."""
    sec = secrets()
    keys = []
    for k in [sec["meta_api_key"], *sec["extra_meta_keys"]]:
        if k and k not in keys:
            keys.append(k)
    return keys


def save_secrets(values: dict) -> None:
    """``None`` keeps a secret, ``""`` clears it, any other string replaces it."""
    with _lock:
        current = secrets()
        for key in SECRET_KEYS:
            if values.get(key) is None:
                continue
            if key == "extra_meta_keys":
                raw = values[key]
                items = raw.splitlines() if isinstance(raw, str) else list(raw)
                current[key] = [s.strip() for s in items if str(s).strip()]
            else:
                current[key] = str(values[key]).strip()
        path = _secrets_path()
        tmp = path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(current, fh)
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:  # pragma: no cover - Windows ACLs
            pass


def public_settings() -> dict:
    s, sec = settings(), secrets()
    out = dict(s)
    for key in ("meta_api_key", "archivist_password"):
        value = sec[key]
        out[f"{key}_set"] = bool(value)
        out[f"{key}_hint"] = f"…{value[-4:]}" if len(value) >= 8 else ("set" if value else "")
    out["extra_meta_keys_count"] = len(sec["extra_meta_keys"])
    out["extra_meta_keys_hints"] = [f"…{k[-4:]}" for k in sec["extra_meta_keys"]]
    return out


def missing_settings() -> list[dict]:
    """What blocks processing/export, in the order the user should fix it."""
    s, sec = settings(), secrets()
    missing = []
    if not s["ejee_db"] or not Path(s["ejee_db"]).is_file():
        missing.append({"key": "ejee_db", "label": "EJEE database file"})
    if not s["uploads"] or not Path(s["uploads"]).is_dir():
        missing.append({"key": "uploads", "label": "EJEE uploads folder"})
    if not sec["meta_api_key"]:
        missing.append({"key": "meta_api_key", "label": "Meta API key"})
    if not s["server_url"]:
        missing.append({"key": "server_url", "label": "PaperLab server link"})
    if not sec["archivist_password"]:
        missing.append({"key": "archivist_password", "label": "Archivist password"})
    return missing


# ---------------------------------------------------------------------- cart
def cart() -> list[dict]:
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM cart ORDER BY rowid")]  # order added


def cart_add(slug, source, part, questions):
    with connect() as c:
        if c.execute("SELECT 1 FROM jobs WHERE slug=? AND part=?", (slug, part)).fetchone():
            raise ValueError("This part is already in the process queue.")
        c.execute("INSERT OR IGNORE INTO cart (slug, source, part, questions, added_at) VALUES (?,?,?,?,?)",
                  (slug, source, part, questions, now()))


def cart_remove(slug, part=None):
    with connect() as c:
        if part is None:
            c.execute("DELETE FROM cart" if slug is None else "DELETE FROM cart WHERE slug=?",
                      () if slug is None else (slug,))
        else:
            c.execute("DELETE FROM cart WHERE slug=? AND part=?", (slug, part))


# ---------------------------------------------------------------------- jobs
def _job(row) -> dict:
    job = dict(row)
    job["done"] = json.loads(job["done"] or "[]")
    job["receipt"] = json.loads(job["receipt"]) if job["receipt"] else None
    job["detail"] = json.loads(job["detail"]) if job["detail"] else None
    return job


def jobs() -> list[dict]:
    with connect() as c:
        return [_job(r) for r in c.execute("SELECT * FROM jobs ORDER BY id")]


def book_started(slug) -> bool:
    """True once any part of the book has run (its plan may be published from)."""
    with connect() as c:
        row = c.execute("SELECT 1 FROM jobs WHERE slug=? AND (status IN ('done','running','failed') "
                        "OR done != '[]') LIMIT 1", (slug,)).fetchone()
    return row is not None


def job(job_id) -> dict | None:
    with connect() as c:
        row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return _job(row) if row else None


def enqueue_cart() -> list[int]:
    """Move every cart part into the job queue (one job per part)."""
    with connect() as c:
        ids = []
        for row in c.execute("SELECT * FROM cart ORDER BY rowid").fetchall():  # books in the order added
            cur = c.execute(
                "INSERT OR IGNORE INTO jobs (slug, source, part, questions, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?)", (row["slug"], row["source"], row["part"], row["questions"], now(), now()))
            if cur.lastrowid and cur.rowcount:
                ids.append(cur.lastrowid)
        c.execute("DELETE FROM cart")
    return ids


def claim_next_job() -> dict | None:
    """Atomically take the first queued part (parallel workers never collide)."""
    for _ in range(50):
        with connect() as c:
            row = c.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
            if not row:
                return None
            cur = c.execute("UPDATE jobs SET status='running', updated_at=? WHERE id=? AND status='queued'",
                            (now(), row["id"]))
            if cur.rowcount == 1:  # we won it; another worker may have taken it between SELECT and UPDATE
                return _job(c.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone())
    return None


def update_job(job_id, **fields):
    for key in ("done", "receipt", "detail"):
        if key in fields and not isinstance(fields[key], (str, type(None))):
            fields[key] = json.dumps(fields[key], ensure_ascii=False)
    fields["updated_at"] = now()
    cols = ", ".join(f"{k}=?" for k in fields)
    with connect() as c:
        c.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), job_id))


def remove_job(job_id):
    with connect() as c:
        c.execute("DELETE FROM jobs WHERE id=?", (job_id,))


def queue_state() -> dict:
    with connect() as c:
        row = c.execute("SELECT paused, reason, kind FROM queue WHERE id=1").fetchone()
    return {"paused": bool(row["paused"]), "reason": row["reason"], "kind": row["kind"]}


def set_queue(paused: bool, reason=None, kind=None):
    with connect() as c:
        c.execute("UPDATE queue SET paused=?, reason=?, kind=? WHERE id=1", (1 if paused else 0, reason, kind))


def recover_interrupted():
    """On startup a 'running' job was interrupted mid-stage: queue it again.

    Completed stages are recorded, so it resumes at the interrupted stage.
    The queue stays paused until the user presses Resume.
    """
    with connect() as c:
        n = c.execute("UPDATE jobs SET status='queued', updated_at=? WHERE status='running'", (now(),)).rowcount
        if n:
            c.execute("UPDATE queue SET paused=1, reason=?, kind='restart' WHERE id=1",
                      (f"The app stopped while {n} part(s) were processing. Press Resume to continue "
                       "from the interrupted step.",))
    return n


def part_statuses() -> dict:
    """{(slug, part): status} for cart + jobs (cart parts report 'in_cart')."""
    out = {}
    with connect() as c:
        for r in c.execute("SELECT slug, part FROM cart"):
            out[(r["slug"], r["part"])] = "in_cart"
        for r in c.execute("SELECT slug, part, status FROM jobs"):
            out[(r["slug"], r["part"])] = {"done": "published"}.get(r["status"], r["status"])
    return out
