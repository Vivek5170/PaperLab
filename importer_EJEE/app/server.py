"""EJEE Importer: an independent local app next to PaperLab.

    python importer_EJEE/app/server.py            # http://127.0.0.1:8030/

Search everything in an EJEE database, collect 15-question parts in a cart,
process them (transcribe + crop + tag + verify), and publish each finished
part to a PaperLab server through its archivist bundle API.

It never imports the PaperLab backend or frontend; it shares only the
importer's own code and run folders. It listens on loopback only, and every
state-changing request must carry the app's own header (so other websites
cannot drive it), because it holds a paid API key and the archivist password.
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import urllib.parse
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

APP = Path(__file__).resolve().parent
sys.path.insert(0, str(APP))

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

import ejee_index  # noqa: E402
import images  # noqa: E402
import pipeline  # noqa: E402
import remote  # noqa: E402
import store  # noqa: E402

BUILD = APP / "web" / "build"
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
CSRF_HEADER = "x-ejee-app"


def public_hosts() -> set[str]:
    """Extra host names allowed besides loopback (e.g. a demo tunnel).

    Off by default. Set with ``--public-host NAME`` or ``EJEE_APP_PUBLIC_HOSTS``
    (comma-separated, exact names). Anyone who reaches such a host can use
    the saved key and archivist password, so only enable it deliberately.
    """
    raw = os.environ.get("EJEE_APP_PUBLIC_HOSTS", "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}

worker = pipeline.Pool()


@asynccontextmanager
async def lifespan(_app):
    _startup()
    try:
        yield
    finally:
        worker.shutdown()


app = FastAPI(title="EJEE Importer", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


# ------------------------------------------------------------------ security
@app.middleware("http")
async def guard(request: Request, call_next):
    host = request.headers.get("host", "")
    hostname = urllib.parse.urlsplit("//" + host).hostname if host else None
    if hostname not in LOOPBACK and hostname not in public_hosts():
        return JSONResponse({"detail": "This app only answers on 127.0.0.1 / localhost."}, status_code=421)
    if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
        if request.headers.get(CSRF_HEADER) != "1":
            return JSONResponse({"detail": "Missing app header."}, status_code=403)
        origin = request.headers.get("origin")
        if origin and urllib.parse.urlsplit(origin).netloc != host:
            return JSONResponse({"detail": "Cross-origin request refused."}, status_code=403)
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
    if request.url.path.startswith("/api/") and not request.url.path.startswith("/api/image/"):
        response.headers["Cache-Control"] = "no-store"
    return response


AUTO_RESUME_KINDS = {"restart", "network", "busy", "rate"}  # never 'meta' or 'auth': those need a person


def _autoresume_loop():
    """Unattended mode (``--auto-resume``): after a restart, sleep or network
    drop, resume the queue once the free server/key checks pass again."""
    worker.stop_flag.wait(20)  # give a co-started PaperLab time to come up
    while not worker.stop_flag.is_set():
        import time
        for w in getattr(worker, "workers", []):  # rate-limited keys get another try after 15 min
            if w.parked and getattr(w, "parked_kind", None) == "rate" and time.time() - w.parked_at > 900:
                w.parked = None
                print(f"{store.now()} auto-resume: key {w.slot + 1} back after rate-limit cooldown", flush=True)
        try:
            q = store.queue_state()
            if q["paused"] and q["kind"] in AUTO_RESUME_KINDS and any(j["status"] == "queued" for j in store.jobs()):
                _preflight()
                worker.resume()
                print(f"{store.now()} auto-resume: queue resumed (was: {q['kind']})", flush=True)
        except HTTPException as exc:
            print(f"{store.now()} auto-resume: not yet ({exc.detail})", flush=True)  # still offline
        except Exception as exc:  # never let the unattended loop die
            print(f"{store.now()} auto-resume: error {type(exc).__name__}: {exc}", flush=True)
        worker.stop_flag.wait(120)


def _startup():
    store.recover_interrupted()
    worker.start()
    if os.environ.get("EJEE_APP_AUTORESUME") == "1":
        threading.Thread(target=_autoresume_loop, name="ejee-autoresume", daemon=True).start()
    s = store.settings()
    if s["ejee_db"] and s["uploads"] and Path(s["ejee_db"]).is_file() and Path(s["uploads"]).is_dir():
        st = ejee_index.status(s["ejee_db"], s["uploads"])
        if not st["built"]:
            ejee_index.build_async(s["ejee_db"], s["uploads"])


def _index_ready():
    if not ejee_index.index_path().is_file() or not ejee_index.status()["built"]:
        raise HTTPException(409, "The EJEE search index is not built yet. Set the EJEE paths in Settings.")


def _source_paths():
    s = store.settings()
    if not (s["ejee_db"] and Path(s["ejee_db"]).is_file()):
        raise HTTPException(409, "Set the EJEE database file in Settings first.")
    if not (s["uploads"] and Path(s["uploads"]).is_dir()):
        raise HTTPException(409, "Set the EJEE uploads folder in Settings first.")
    return s


# -------------------------------------------------------------------- status
@app.get("/api/health")
def health():
    return {"ok": True, "app": "ejee-importer"}


@app.get("/api/status")
def status():
    s = store.settings()
    jobs = store.jobs()
    counts = {k: 0 for k in ("queued", "running", "needs_review", "failed", "done")}
    for j in jobs:
        counts[j["status"]] = counts.get(j["status"], 0) + 1
    spent = sum(j["usd"] or 0 for j in jobs)
    return {"missing": store.missing_settings(),
            "index": ejee_index.status(s["ejee_db"] or None, s["uploads"] or None),
            "queue": store.queue_state(), "worker": worker.running(),
            "cart": len(store.cart()), "jobs": counts, "spent": pipeline.money(spent)}


@app.post("/api/index/rebuild")
def rebuild_index():
    s = _source_paths()
    started = ejee_index.build_async(s["ejee_db"], s["uploads"])
    return {"started": started, "index": ejee_index.status()}


# -------------------------------------------------------------------- search
class Filters(BaseModel):
    q: str = ""
    category: list[str] = []
    source: list[str] = []
    qtype: list[str] = []
    difficulty: list[str] = []
    exam: list[str] = []
    year: list[str] = []
    answer: list[str] = []
    status: list[str] = []
    topic: list[str] = []
    convertible: bool = False


class SearchBody(BaseModel):
    filters: Filters = Filters()
    cursor: int = Field(0, ge=0)
    limit: int = Field(24, ge=1, le=60)


@app.post("/api/search")
def search(body: SearchBody):
    _index_ready()
    return ejee_index.search(body.filters.model_dump(), store.part_statuses(), body.cursor, body.limit)


@app.post("/api/facets")
def facets(body: SearchBody):
    _index_ready()
    return ejee_index.facets(body.filters.model_dump(), store.part_statuses())


@app.get("/api/topics")
def topics():
    _index_ready()
    return ejee_index.topics()


@app.get("/api/item")
def item(key: str, source: str):
    _index_ready()
    found = ejee_index.item(key, source, store.part_statuses())
    if not found:
        raise HTTPException(404, "Item not found in the index.")
    return found


@app.get("/api/image/{rid}")
def image(rid: int, w: int = 480, full: bool = False):
    s = _source_paths()
    try:
        got = images.preview(s["ejee_db"], s["uploads"], rid, w, full)
    except Exception:
        got = None
    if not got:
        raise HTTPException(404, "Image not available.")
    return Response(got[0], media_type=got[1], headers={"Cache-Control": "private, max-age=86400"})


@app.get("/api/part/{slug}/{part}")
def part(slug: str, part: int):
    _index_ready()
    info = ejee_index.part_info(slug, part)
    if not info:
        raise HTTPException(404, "Part not found.")
    info["status"] = store.part_statuses().get((slug, part), "not_started")
    return info


# ---------------------------------------------------------------------- cart
class CartAdd(BaseModel):
    slug: str
    part: int = Field(ge=1)


@app.get("/api/cart")
def cart():
    items = []
    for row in store.cart():
        info = ejee_index.part_info(row["slug"], row["part"]) if ejee_index.index_path().is_file() else None
        items.append({**row, **(info or {}), "added_at": row["added_at"]})
    return {"items": items, "questions": sum(i["questions"] for i in items)}


@app.post("/api/cart")
def cart_add(body: CartAdd):
    _index_ready()
    s = _source_paths()
    info = ejee_index.part_info(body.slug, body.part)
    if not info:
        raise HTTPException(404, "Part not found.")
    try:
        plan = pipeline.ensure_plan(info["source"], body.slug, s["ejee_db"], s["uploads"])
    except Exception as exc:
        raise HTTPException(409, f"Could not plan {info['source']}: {exc}")
    if body.part > len(plan["parts"]) or plan["parts"][body.part - 1] != info["keys"]:
        ejee_index.refresh_planned(info["source"], body.slug, plan)
        raise HTTPException(409, "The frozen plan for this book differs from the search index (EJEE changed). "
                                 "The index was updated; search again and re-add the part.")
    if not info["planned"]:
        ejee_index.refresh_planned(info["source"], body.slug, plan)
        _freeze_plan_file(body.slug, plan)
    try:
        store.cart_add(body.slug, info["source"], body.part, info["questions"])
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return cart()


class BooksQuery(BaseModel):
    q: str = ""
    category: list[str] = []


@app.post("/api/books")
def books(body: BooksQuery):
    _index_ready()
    return {"books": ejee_index.books(body.q, body.category, store.part_statuses()),
            "categories": ejee_index.CATEGORIES}


def _freeze_plan_file(slug: str, plan: dict):
    """Write the frozen plan the index used (plan/plan.json) for reproducibility."""
    import json as _json
    path = (store.ROOT / store.runs_rel() / slug / "plan.json")
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json.dumps(plan, indent=1, ensure_ascii=False), encoding="utf-8")


def parse_parts(text: str, total: int) -> list[int]:
    """'all', '3', '1-5', '1-3,8,10-12' -> sorted part numbers within 1..total."""
    text = (text or "all").strip().lower()
    if text in ("", "all"):
        return list(range(1, total + 1))
    parts = set()
    for chunk in text.replace(" ", "").split(","):
        bounds = chunk.split("-", 1)
        try:
            a, b = int(bounds[0]), int(bounds[-1])
        except ValueError:
            raise HTTPException(422, f"Use part numbers like 1-5 or 1,4,7 (got {chunk!r}).")
        if not 1 <= a <= b <= total:
            raise HTTPException(422, f"Parts must be between 1 and {total} (got {chunk!r}).")
        parts.update(range(a, b + 1))
    return sorted(parts)


class BookConvert(BaseModel):
    slug: str
    parts: str = "all"


@app.post("/api/books/cart")
def book_to_cart(body: BookConvert):
    """Convert a book: freeze its plan, then put the chosen parts in the cart.
    Parts already in the cart, queued, processing or published are skipped."""
    _index_ready()
    s = _source_paths()
    src = ejee_index.source_by_slug(body.slug)
    if not src:
        raise HTTPException(404, "Book not found.")
    try:
        plan = pipeline.ensure_plan(src["source"], body.slug, s["ejee_db"], s["uploads"])
    except Exception as exc:
        raise HTTPException(409, f"Could not plan {src['source']}: {exc}")
    ejee_index.refresh_planned(src["source"], body.slug, plan)
    _freeze_plan_file(body.slug, plan)
    taken = store.part_statuses()
    added, skipped = [], []
    for part in parse_parts(body.parts, len(plan["parts"])):
        if (body.slug, part) in taken:
            skipped.append(part)
            continue
        try:
            store.cart_add(body.slug, src["source"], part, len(plan["parts"][part - 1]))
            added.append(part)
        except ValueError:
            skipped.append(part)
    return {"added": added, "skipped": skipped, "source": src["source"],
            "questions": sum(len(plan["parts"][p - 1]) for p in added)}


@app.delete("/api/cart/{slug}/{part}")
def cart_remove(slug: str, part: int):
    store.cart_remove(slug, part)
    return cart()


@app.delete("/api/cart")
def cart_clear():
    store.cart_remove(None)
    return cart()


# ------------------------------------------------------------------ settings
class SettingsBody(BaseModel):
    server_url: str | None = None
    ejee_db: str | None = None
    uploads: str | None = None
    meta_api_key: str | None = None
    archivist_password: str | None = None
    extra_meta_keys: list[str] | None = None  # one parallel worker per key


@app.get("/api/settings")
def get_settings():
    return store.public_settings()


@app.put("/api/settings")
def put_settings(body: SettingsBody):
    values = body.model_dump()
    if values.get("server_url"):
        try:
            values["server_url"] = remote.normalize_url(values["server_url"])
        except remote.RemoteError as exc:
            raise HTTPException(422, str(exc))
    for key, kind in (("ejee_db", "file"), ("uploads", "folder")):
        if values.get(key):
            path = Path(values[key].strip().strip('"')).expanduser()
            ok = path.is_file() if kind == "file" else path.is_dir()
            if not ok:
                raise HTTPException(422, f"{'EJEE database file' if kind == 'file' else 'Uploads folder'} "
                                         f"not found: {path}")
            values[key] = str(path.resolve())
    before = store.settings()
    store.save_settings(values)
    store.save_secrets({k: values.get(k) for k in store.SECRET_KEYS})
    worker.ensure()  # a newly added key starts its own worker right away
    after = store.settings()
    if (after["ejee_db"], after["uploads"]) != (before["ejee_db"], before["uploads"]) \
            and after["ejee_db"] and after["uploads"]:
        st = ejee_index.status(after["ejee_db"], after["uploads"])
        if not st["built"] or st["stale"]:
            ejee_index.build_async(after["ejee_db"], after["uploads"])
    return store.public_settings()


class TestBody(BaseModel):
    what: str


@app.post("/api/settings/test")
def test_settings(body: TestBody):
    s, sec = store.settings(), store.secrets()
    try:
        if body.what == "server":
            if not s["server_url"] or not sec["archivist_password"]:
                raise HTTPException(400, "Save the server link and archivist password first.")
            return remote.check_server(s["server_url"], sec["archivist_password"])
        if body.what == "meta":
            results = []
            for i, key in enumerate(store.meta_keys(), 1):
                try:
                    r = remote.check_meta_key(key, pipeline.model_base_url())
                    results.append({"key": i, "hint": f"…{key[-4:]}", **r})
                except remote.RemoteError as exc:
                    results.append({"key": i, "hint": f"…{key[-4:]}", "ok": False, "kind": exc.kind,
                                    "detail": str(exc)})
            bad = [r for r in results if not r["ok"]]
            if not results:
                raise remote.RemoteError("meta", "No Meta API key is set.")
            return {"ok": not bad, "keys": results,
                    "verified": all(r.get("verified") for r in results),
                    "detail": "; ".join(f"key {r['key']} ({r['hint']}): {r['detail']}" for r in bad) or None,
                    "note": f"{len(results)} key(s): " + ", ".join(
                        f"{r['hint']} {'ok' if r['ok'] else 'REJECTED'}" for r in results)}
        if body.what == "source":
            _source_paths()
            return {"ok": True, "index": ejee_index.status(s["ejee_db"], s["uploads"])}
    except remote.RemoteError as exc:
        return JSONResponse({"ok": False, "kind": exc.kind, "detail": str(exc)}, status_code=200)
    raise HTTPException(400, "Unknown test.")


# ------------------------------------------------------------------- process
def _preflight():
    """Free checks before any paid call: settings complete, server + key OK."""
    missing = store.missing_settings()
    if missing:
        raise HTTPException(400, {"message": "Finish Settings first: " + ", ".join(m["label"] for m in missing),
                                  "missing": missing})
    s, sec = store.settings(), store.secrets()
    try:
        remote.check_server(s["server_url"], sec["archivist_password"])
    except remote.RemoteError as exc:
        raise HTTPException(400, {"message": str(exc), "kind": exc.kind})
    errors = []
    for i, key in enumerate(store.meta_keys(), 1):
        try:
            remote.check_meta_key(key, pipeline.model_base_url())
            return  # at least one working key is enough to start; bad ones bench themselves
        except remote.RemoteError as exc:
            errors.append((exc, f"key {i}: {exc}"))
    if errors:
        exc = errors[0][0]
        raise HTTPException(400, {"message": "; ".join(e[1] for e in errors), "kind": exc.kind})


@app.get("/api/jobs")
def jobs():
    out = []
    for j in store.jobs():
        j["money"] = pipeline.money(j["usd"] or 0)
        j["bundle"] = Path(j["bundle"]).name if j["bundle"] else None
        out.append(j)
    return {"jobs": out, "queue": store.queue_state(), "worker": worker.running(), "stages": store.STAGES}


@app.post("/api/process/start")
def process_start():
    if not store.cart() and not any(j["status"] == "queued" for j in store.jobs()):
        raise HTTPException(400, "The cart is empty.")
    _preflight()
    store.enqueue_cart()
    worker.resume()
    return jobs()


@app.post("/api/process/pause")
def process_pause():
    worker.pause()
    return jobs()


@app.post("/api/process/resume")
def process_resume():
    _preflight()
    worker.resume()
    return jobs()


def _job_or_404(job_id):
    job = store.job(job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    return job


@app.post("/api/jobs/{job_id}/retry")
def job_retry(job_id: int):
    job = _job_or_404(job_id)
    if job["status"] in ("running", "done"):
        raise HTTPException(409, f"This part is {job['status']}.")
    store.update_job(job_id, status="queued", error=None, error_kind=None)
    worker.wake.set()
    return jobs()


@app.delete("/api/jobs/{job_id}")
def job_remove(job_id: int):
    job = _job_or_404(job_id)
    if job["status"] == "running":
        raise HTTPException(409, "Pause the queue and wait for this part to stop first.")
    store.remove_job(job_id)
    return jobs()


@app.get("/api/jobs/{job_id}/log")
def job_log(job_id: int):
    return {"log": pipeline.log_tail(_job_or_404(job_id))}


# ----------------------------------------------------------------------- SPA
@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404, "Not found.")
    if not (BUILD / "index.html").is_file():
        return HTMLResponse("<h1>EJEE Importer</h1><p>The web UI is not built. Run "
                            "<code>npm --prefix importer_EJEE/app/web ci</code> and "
                            "<code>npm --prefix importer_EJEE/app/web run build</code>, then restart.</p>",
                            status_code=503)
    target = (BUILD / path).resolve() if path else None
    if target and BUILD.resolve() in target.parents and target.is_file():
        cache = "public, max-age=31536000, immutable" if "/_app/immutable/" in "/" + path else "no-cache"
        return FileResponse(target, headers={"Cache-Control": cache})
    return FileResponse(BUILD / "index.html", headers={"Cache-Control": "no-cache"})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=int(os.environ.get("EJEE_APP_PORT", 8030)))
    ap.add_argument("--host", default="127.0.0.1", help="loopback only: 127.0.0.1, localhost or ::1")
    ap.add_argument("--open", action="store_true", help="open the browser")
    ap.add_argument("--public-host", action="append", default=[], metavar="NAME",
                    help="also answer for this exact host name (e.g. a tunnel); exposes the saved key and "
                         "password to anyone who reaches it")
    ap.add_argument("--auto-resume", action="store_true",
                    help="unattended: resume the queue by itself after a restart, sleep or network drop")
    ap.add_argument("--bundle-copy", metavar="DIR",
                    help="also copy every exported bundle into DIR/<book>/ (e.g. a OneDrive folder)")
    args = ap.parse_args()
    if args.auto_resume:
        os.environ["EJEE_APP_AUTORESUME"] = "1"
    if args.bundle_copy:
        os.environ["EJEE_APP_BUNDLE_COPY"] = str(Path(args.bundle_copy).resolve())
    if args.public_host:
        os.environ["EJEE_APP_PUBLIC_HOSTS"] = ",".join(
            filter(None, [os.environ.get("EJEE_APP_PUBLIC_HOSTS", ""), *args.public_host]))
        print(f"warning: also answering for {', '.join(args.public_host)}; anyone reaching it can spend "
              "your key and publish with your password.", flush=True)
    if args.host not in LOOPBACK:
        raise SystemExit("The EJEE Importer holds an API key and the archivist password; it only listens on "
                         "loopback (127.0.0.1, localhost or ::1).")
    if not (BUILD / "index.html").is_file():
        print("warning: web UI not built (npm --prefix importer_EJEE/app/web ci && ... run build)", flush=True)
    import uvicorn
    url = f"http://{'[::1]' if args.host == '::1' else args.host}:{args.port}/"
    print(f"EJEE Importer on {url}  (Ctrl+C to stop)", flush=True)
    if args.open:
        webbrowser.open(url)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
