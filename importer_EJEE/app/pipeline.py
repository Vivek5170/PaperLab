"""Processing queue: cart parts -> staged run -> .plbundle -> PaperLab server.

One background worker processes jobs one at a time, in this order:

    prepare, extract, figures, pack, classify, verify, export, upload

Each job records the stages it has completed. A retry/resume always starts
at the first stage NOT completed, so nothing finished is redone and nothing
already paid for is billed again (extract/classify also skip finished
questions internally). The run folders are the same ones ``run_book.py``
uses, so the CLI and the app can continue each other's work.

There is no human review step (direct mode). When the only verification
findings are review holds (a figure crop touching an edge, crop attempts
used up), the app records an approval by ``AUTO_BY`` -- which says plainly
that nobody reviewed it -- verifies again and continues. The note travels
in the bundle, and each job lists the questions published this way.

Failures fall in two groups:

* **Settings / connectivity** (Meta key rejected, model endpoint or PaperLab
  server unreachable, wrong archivist password, rate limit): the whole
  queue pauses with the reason. Every other part would hit the same wall.
  Fix Settings and press Resume; the job continues at the stage that failed.
* **Content** (a question that still fails after a retry, invalid TeX, a
  bundle the server rejects): that job fails with the reason; others go on.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from collections import deque
from contextlib import closing
from pathlib import Path

import remote
import store
from store import ROOT, STAGES

IMPORTER = ROOT / "importer.py"
sys.path.insert(0, str(ROOT))

PRICE = {"input": 0.10, "cached": 0.002, "output": 0.20}  # USD per million tokens (config.yaml)
USD_INR = float(os.environ.get("USD_INR", "92.89"))
GST = 0.18

_META = re.compile(r"AuthenticationError|PermissionDeniedError|\b401\b|\b403\b|invalid[_ ]api[_ ]key|"
                   r"Incorrect API key|META_API_KEY is missing|Unauthorized|api key", re.I)
_RATE = re.compile(r"RateLimitError|\b429\b|insufficient_quota|quota exceeded", re.I)
_NET = re.compile(r"APIConnectionError|APITimeoutError|ConnectError|ConnectTimeout|getaddrinfo|"
                  r"Name or service not known|Temporary failure in name resolution|Connection refused|"
                  r"Connection reset|ReadTimeout|NetworkError|timed out|No route to host", re.I)
REVIEW_ERRORS = ("Unresolved extraction review", "files changed after approval",
                 "crop edge review required", "unreadable content requires review")
AUTO_BY = "EJEE Importer app (automatic, no human review)"
AUTO_NOTE = "Direct publish: held items were not reviewed by a person."


# Exit codes that mean "the OS stopped the child" (shutdown, logoff, Ctrl+C,
# console closed), not "this part is bad": 0x40010004 DBG_TERMINATE_PROCESS,
# 0xC000013A STATUS_CONTROL_C_EXIT, 0xC000026B DLL init failed during logoff,
# 0xC0000142 DLL init failed; negative = POSIX signal.
_KILLED = {0x40010004, 0xC000013A, 0xC000026B, 0xC0000142}


class Interrupted(Exception):
    """A phase was killed from outside; resume it later, do not fail the part."""


class Stalled(Exception):
    """A phase printed nothing for STALL_SEC (e.g. a model request that never returns)."""


MAX_UPLOAD_BYTES = 64 * 1024 * 1024  # PaperLab POST /api/bundles/import body limit (backend/routers/bundles.py)
STALLED_RC = 0x5A11ED  # our own exit marker for a phase killed by the silence guard
MAX_STALLS = 3


def stall_sec() -> float:
    return float(os.environ.get("EJEE_APP_STALL_SEC", 1200))


def was_killed(rc: int) -> bool:
    return rc < 0 or (rc & 0xFFFFFFFF) in _KILLED


def classify_failure(text: str) -> str | None:
    """'meta' | 'rate' | 'network' for systemic model failures, else None."""
    if not text:
        return None
    if _META.search(text):
        return "meta"
    if _RATE.search(text):
        return "rate"
    if _NET.search(text):
        return "network"
    return None


def run_dir(slug: str, part: int) -> Path:
    return ROOT / store.runs_rel() / slug / f"part-{part:03d}"


def cost(run: Path) -> float:
    import sqlite3
    db = run / "paperlab.db"
    if not db.is_file():
        return 0.0
    with closing(sqlite3.connect(db)) as c:
        try:
            row = c.execute("SELECT sum(input), sum(cache_read), sum(output) FROM token_usage").fetchone()
        except sqlite3.Error:
            return 0.0
    inp, cached, out = (v or 0 for v in row)
    return ((inp - cached) * PRICE["input"] + cached * PRICE["cached"] + out * PRICE["output"]) / 1e6


def money(usd: float) -> dict:
    return {"usd": round(usd, 4), "inr": round(usd * USD_INR, 2),
            "inr_gst": round(usd * USD_INR * (1 + GST), 2), "rate": USD_INR}


def model_base_url() -> str:
    try:
        import yaml
        cfg = yaml.safe_load((ROOT.parent / "config.yaml").read_text(encoding="utf-8")) or {}
        return (cfg.get("llm") or {}).get("base_url") or "https://api.meta.ai/v1"
    except Exception:
        return "https://api.meta.ai/v1"


# --------------------------------------------------------------------- plans
def answered_only(source: str) -> bool:
    """Hibbeler, Savchenko and Meriam process only questions with a key or a worked solution."""
    from ejee_index import in_answered_only
    return in_answered_only(source)


def ensure_plan(source: str, slug: str, ejee_db: str, uploads: str) -> dict:
    """Freeze (or load) the book plan, exactly as run_book.py does.

    Answered-only books: a plan already trimmed (``_trim``) is frozen and loaded
    as-is -- its earlier parts may be published, so it is never re-cut. An
    untrimmed plan is re-frozen answered-only only while nothing of the book has
    started; otherwise this refuses (re-cutting would renumber published parts).
    """
    import book_plan
    from importer import source_connect
    book_dir = ROOT / store.runs_rel() / slug
    plan_path = book_dir / "plan.json"
    if answered_only(source):
        old = json.loads(plan_path.read_text(encoding="utf-8")) if plan_path.exists() else None
        if old is not None:
            if old.get("source") != source:
                raise ValueError(f"{plan_path} belongs to another source ({old.get('source')!r}).")
            if old.get("_trim"):
                return old
            if store.book_started(slug):
                raise ValueError(f"{source!r} has an untrimmed plan and parts already started; "
                                 "trim it from the first unstarted part (scripts/trim_answered.py).")
        with closing(source_connect(ejee_db)) as conn:
            items, _ignored = book_plan.load_book(conn, source, uploads)
        ok = [it for it in items if it["solution_ids"] or it["has_key"]]
        if not ok:
            raise ValueError(f"No answered questions in {source!r}.")
        parts = [[it["key"] for it in chunk] for chunk in book_plan.cut_parts(ok, 15)]
        plan = {"schema": book_plan.PLAN_SCHEMA, "source": source, "part_size": 15,
                "parts": parts, "items": {it["key"]: it for it in items},
                "_trim": {"from_part": 1, "policy": "answered items only (key or worked solution)"}}
        book_dir.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(json.dumps(plan, indent=1, ensure_ascii=False), encoding="utf-8")
        return plan
    if not plan_path.exists():
        with closing(source_connect(ejee_db)) as conn:
            summary = book_plan.plan_book(conn, source, uploads, 15, book_dir)
        if not summary["ready"]:
            raise ValueError(f"No importable questions in {source!r}.")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("source") != source:
        raise ValueError(f"{plan_path} belongs to another source ({plan.get('source')!r}).")
    return plan


def write_config(job: dict, ejee_db: str, uploads: str) -> Path:
    run = run_dir(job["slug"], job["part"])
    run.mkdir(parents=True, exist_ok=True)
    cfg_path = run.parent / f"part-{job['part']:03d}.json"
    cfg_path.write_text(json.dumps({
        "source_db": str(Path(ejee_db).resolve()), "asset_root": str(Path(uploads).resolve()),
        "book_source": job["source"], "part": job["part"], "book_plan": str(run.parent / "plan.json"),
        "run_dir": run.relative_to(ROOT).as_posix(), "native_figure_cleanup": True,
        # Direct mode: a question Node 3 declined to tag is published untagged
        # and goes to PaperLab's Tagging Inbox instead of blocking the part.
        "allow_untagged": True}, indent=1), encoding="utf-8")
    return cfg_path


def default_runner(phase: str, cfg_path: Path, log_path: Path, env: dict, args=(), on_proc=None) -> tuple[int, str]:
    """Run one importer phase in a child process; append output to the part log."""
    tail = deque(maxlen=200)
    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"\n===== {phase} (EJEE Importer app, {store.now()})\n")
        log.flush()
        proc = subprocess.Popen([sys.executable, str(IMPORTER), phase, "--config", str(cfg_path), *args],
                                cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace",
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))  # no console pop-ups (Windows)
        if on_proc:
            on_proc(proc)
        last = [time.monotonic()]
        stalled = threading.Event()
        finished = threading.Event()
        limit = stall_sec()

        def guard():  # kill a child that has gone silent (hung request, no timeout)
            while not finished.wait(5):
                if time.monotonic() - last[0] > limit:
                    stalled.set()
                    proc.kill()
                    return

        threading.Thread(target=guard, name=f"stall-guard-{phase}", daemon=True).start()
        for line in proc.stdout:
            last[0] = time.monotonic()
            log.write(line)
            log.flush()
            tail.append(line.rstrip("\n"))
        rc = proc.wait()
        finished.set()
        if stalled.is_set():
            log.write(f"===== {phase} killed: no output for {limit:.0f}s (stall guard)\n")
            return STALLED_RC, "\n".join(tail)
        log.write(f"===== {phase} exit {rc}\n")
    return rc, "\n".join(tail)


def child_env(meta_key: str | None) -> dict:
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    env.pop("META_API_KEY", None)
    if meta_key:
        env["META_API_KEY"] = meta_key  # passed in memory only; never written to .env
    return env


# -------------------------------------------------------------------- worker
class Pipeline:
    """One worker. ``slot`` picks its Meta key (0 = primary key, 1.. = extra keys)."""

    def __init__(self, runner=default_runner, publisher=remote.publish, slot=0, pool=None):
        self.runner = runner
        self.publisher = publisher
        self.slot = slot
        self.pool = pool
        self.parked = None  # reason this worker's key is benched (others keep going)
        self.wake = threading.Event()
        self.stop_flag = threading.Event()
        self.current = None  # job id
        self.proc = None
        self.thread = None

    def key(self) -> str | None:
        keys = store.meta_keys()
        if not keys or self.slot >= len(keys) * workers_per_key():
            return None
        return keys[self.slot % len(keys)]  # slots 0..n-1 = one per key, n..2n-1 = second per key, ...

    # control ------------------------------------------------------------
    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._loop, name=f"ejee-pipeline-{self.slot}", daemon=True)
        self.thread.start()

    def resume(self):
        store.set_queue(False)
        self.wake.set()

    def pause(self, reason="Paused by you. The current step finishes first.", kind="user"):
        store.set_queue(True, reason, kind)

    def shutdown(self):
        self.stop_flag.set()
        self.wake.set()
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()

    def running(self) -> dict:
        return {"job": self.current}

    # loop -----------------------------------------------------------------
    def _loop(self):
        while not self.stop_flag.is_set():
            q = store.queue_state()
            idle = q["paused"] or self.parked or not self.key()
            nxt = None if idle else store.claim_next_job()
            if nxt is None:
                if self.pool:
                    self.stop_flag.wait(2)  # shared queue: poll, never spin on a set event
                else:
                    self.wake.wait(timeout=2)
                    self.wake.clear()
                continue
            try:
                self.process(nxt)
            except Exception as exc:  # last-resort guard: never kill the worker
                store.update_job(nxt["id"], status="failed", error_kind="internal",
                                 error=f"Unexpected error: {type(exc).__name__}: {exc}")
            finally:
                self.current = None
                self.proc = None

    def _pause_queue(self, job, stage, kind, message):
        store.update_job(job["id"], status="queued", stage=stage, error=message, error_kind=kind)
        # A rejected or rate-limited key only benches this worker while other
        # keys are still working; the last working key pauses the whole queue.
        # (No pool = old single-worker behaviour: always pause the queue.)
        if kind in ("meta", "rate") and self.pool is not None and self.pool.active_count() > 1:
            import time
            self.parked = f"key {self.slot % max(1, len(store.meta_keys())) + 1}: {message}"
            self.parked_kind, self.parked_at = kind, time.time()
            return
        store.set_queue(True, message, kind)

    def process(self, job):
        settings, secrets = store.settings(), store.secrets()
        self.current = job["id"]
        prev = job.get("detail") if isinstance(job.get("detail"), dict) else {}
        keep = {"stalls": prev["stalls"]} if prev.get("stalls") else None  # survives re-pickup
        store.update_job(job["id"], status="running", error=None, error_kind=None, detail=keep,
                         attempts=job["attempts"] + 1)
        done = list(job["done"])
        run = run_dir(job["slug"], job["part"])
        try:
            ensure_plan(job["source"], job["slug"], settings["ejee_db"], settings["uploads"])
            cfg_path = write_config(job, settings["ejee_db"], settings["uploads"])
        except Exception as exc:
            store.update_job(job["id"], status="failed", stage="prepare", error_kind="content",
                             error=f"Could not plan this part: {exc}")
            return
        log_path = run.parent / f"part-{job['part']:03d}.log"
        env = child_env(self.key() or secrets["meta_api_key"])

        if not self._manifest_matches_plan(job, run, cfg_path):
            import shutil  # stale run from a re-planned book: rebuild it cleanly, once
            store.update_job(job["id"], done=[], stage="prepare")
            shutil.rmtree(run, ignore_errors=True)
            run.mkdir(parents=True, exist_ok=True)
            cfg_path = write_config(job, settings["ejee_db"], settings["uploads"])
            done = []
        for stage in STAGES:
            if stage in done:
                continue  # finished stage, manifest still current
            if store.queue_state()["paused"]:
                store.update_job(job["id"], status="queued", stage=stage)
                return
            store.update_job(job["id"], stage=stage)
            try:
                outcome = self._stage(job, stage, run, cfg_path, log_path, env, settings, secrets)
            except Interrupted as exc:
                # Shutdown/logoff/sleep killed the child: keep the part queued at
                # this step and pause, so the rest of the queue is not burned.
                self._pause_queue(job, stage, "restart",
                                  f"Paused: {exc}. Resume continues at this step; finished work is kept.")
                store.update_job(job["id"], usd=round(cost(run), 6))
                return
            except Stalled as exc:
                # One hung child: retry just this part (finished questions are kept);
                # the rest of the queue keeps running. Give up after MAX_STALLS.
                detail = store.job(job["id"]).get("detail") or {}
                stalls = int(detail.get("stalls", 0)) + 1 if isinstance(detail, dict) else 1
                if stalls >= MAX_STALLS:
                    store.update_job(job["id"], status="failed", stage=stage, error_kind="network",
                                     error=f"{exc} ({stalls} times); retry it later.", detail={"stalls": stalls},
                                     usd=round(cost(run), 6))
                else:
                    store.update_job(job["id"], status="queued", stage=stage, error=str(exc),
                                     detail={"stalls": stalls}, usd=round(cost(run), 6))
                return
            store.update_job(job["id"], usd=round(cost(run), 6))
            if outcome is not True:
                return  # the stage already recorded the job/queue state
            done.append(stage)
            store.update_job(job["id"], done=done)
        store.update_job(job["id"], status="done", stage="upload", error=None, error_kind=None)

    def _phase(self, phase, cfg_path, log_path, env, args=()):
        def keep(proc):
            self.proc = proc
        rc, out = self.runner(phase, cfg_path, log_path, env, args, keep)
        if rc == STALLED_RC:
            raise Stalled(f"{phase} went silent for {stall_sec():.0f}s and was restarted")
        if was_killed(rc):
            raise Interrupted(f"{phase} was stopped by the system (exit {rc & 0xFFFFFFFF:#x})")
        return rc, out

    def _manifest_matches_plan(self, job, run, cfg_path) -> bool:
        """The frozen plan changed (answered-only re-plan): restart the run cleanly."""
        manifest = _read_json(run / "manifest.json")
        if not manifest.get("items"):
            return True  # nothing prepared yet: not stale, just new
        try:
            plan = ensure_plan(job["source"], job["slug"], store.settings()["ejee_db"],
                               store.settings()["uploads"])
        except Exception:
            return True  # unknown: don't delete blindly, let prepare fail loudly
        try:
            want = plan["parts"][int(job["part"]) - 1]
        except (IndexError, KeyError, TypeError):
            return True
        return [it.get("plan_key") or it.get("key") for it in (manifest.get("items") or [])] == want

    @staticmethod
    def _abstained(run, number) -> bool:
        """Node 3 answered 'no topic' for this question (not an error)."""
        from importer import is_abstention
        return is_abstention((_read_json(run / "progress.json").get("node3") or {}).get(number) or {})

    def _stage(self, job, stage, run, cfg_path, log_path, env, settings, secrets):
        if stage == "prepare":
            if _read_json(run / "manifest.json").get("items") and self._manifest_matches_plan(job, run, cfg_path):
                return True  # prepared just before a restart (not yet recorded): keep it, go on
            rc, out = self._phase("prepare", cfg_path, log_path, env)
            if rc:
                store.update_job(job["id"], status="failed", error_kind="content",
                                 error="Preparing source pages failed. " + _last_error(out))
                return False
            return True

        if stage in ("extract", "classify"):
            for attempt in (1, 2):
                rc, out = self._phase(stage, cfg_path, log_path, env)
                if rc == 0:
                    return True
                text = out + "\n" + _progress_errors(run, stage)
                kind = classify_failure(text)
                if kind:
                    self._pause_queue(job, stage, kind, _systemic_message(kind, stage))
                    return False
                if attempt == 1:
                    continue  # one automatic retry of just the unfinished questions
            failed = _failed_questions(run, stage)
            if stage == "classify" and failed and all(self._abstained(run, n) for n in failed):
                current = store.job(job["id"])["detail"] or {}
                store.update_job(job["id"], detail={**current, "untagged": failed})
                return True  # published untagged -> PaperLab's Tagging Inbox
            store.update_job(job["id"], status="failed", error_kind="content",
                             detail={"failed": failed},
                             error=(f"{stage.title()} could not finish question(s) {', '.join(failed) or '?'} "
                                    f"after a retry. Retry runs only those again. " + _last_error(out))[:900])
            return False

        if stage in ("figures", "pack"):
            rc, out = self._phase(stage, cfg_path, log_path, env)
            if rc:
                store.update_job(job["id"], status="failed", error_kind="internal",
                                 error=f"{stage.title()} failed. " + _last_error(out))
                return False
            return True

        if stage == "verify":
            rc, out = self._phase("verify", cfg_path, log_path, env)
            if rc == 0:
                return True
            errors = _verify_errors(run)
            review = [e for e in errors if any(m in e for m in REVIEW_ERRORS)]
            other = [e for e in errors if e not in review]
            if review and not other:
                # Direct mode: no human review step. Record an approval that
                # says exactly that (it travels in the bundle's provenance),
                # then verify again; real problems below still fail the part.
                held = _held_questions(run, review)
                rc, out = self._phase("approve", cfg_path, log_path, env, ("--by", AUTO_BY, "--note", AUTO_NOTE))
                if rc:
                    store.update_job(job["id"], status="failed", error_kind="internal",
                                     error="Could not record the automatic approval. " + _last_error(out))
                    return False
                current = store.job(job["id"])["detail"] or {}
                store.update_job(job["id"], detail={**current, "auto_approved": held})
                rc, out = self._phase("verify", cfg_path, log_path, env)
                if rc == 0:
                    return True
                errors = _verify_errors(run)
                other = [e for e in errors if not any(m in e for m in REVIEW_ERRORS)] or errors
            store.update_job(job["id"], status="failed", error_kind="content",
                             detail={"errors": errors},
                             error="Verification found problems: " + "; ".join(other[:4] or [_last_error(out)]))
            return False

        if stage == "export":
            out_file = run / _bundle_name(run)
            if out_file.exists():
                out_file.unlink()  # a new export only happens after verify ran again
            rc, out = self._phase("export", cfg_path, log_path, env, ("--out", str(out_file)))
            if rc or not out_file.is_file():
                store.update_job(job["id"], status="failed", error_kind="internal",
                                 error="Export failed. " + _last_error(out))
                return False
            store.update_job(job["id"], bundle=str(out_file), bundle_sha=_sha(out_file))
            copy_bundle(job, out_file)
            return True

        if stage == "upload":
            current = store.job(job["id"])
            bundle = Path(current["bundle"] or "")
            if not bundle.is_file() or _sha(bundle) != current["bundle_sha"]:
                done = [s for s in current["done"] if s not in ("export", "upload")]
                store.update_job(job["id"], done=done, status="queued", stage="export",
                                 error="The exported bundle changed or disappeared; exporting again.")
                return False
            size = bundle.stat().st_size
            if size > MAX_UPLOAD_BYTES:  # PaperLab drops bigger bodies mid-send (looks like a network error)
                store.update_job(job["id"], status="failed", error_kind="content",
                                 error=f"Bundle is {size / 1e6:.1f} MB, over PaperLab's {MAX_UPLOAD_BYTES >> 20} MB "
                                       "upload limit. Kept on disk, not sent.")
                return False
            try:
                receipt = self.publisher(settings["server_url"], secrets["archivist_password"], bundle)
            except remote.RemoteError as exc:
                if exc.kind in ("network", "auth", "server", "busy"):
                    hint = {"network": "Check the PaperLab server link in Settings.",
                            "auth": "Check the archivist password in Settings.",
                            "server": "The server needs attention (see message).",
                            "busy": "The server is busy; press Resume in a minute."}[exc.kind]
                    self._pause_queue(job, "upload", exc.kind,
                                      f"Upload paused: {exc} {hint} The bundle is kept and will be sent "
                                      "unchanged, so a repeat cannot create a duplicate.")
                    return False
                store.update_job(job["id"], status="failed", error_kind=exc.kind, error=str(exc)[:900])
                return False
            store.update_job(job["id"], receipt=receipt)
            return True
        raise ValueError(stage)


def workers_per_key() -> int:
    """Parallel parts per Meta key (EJEE_APP_WORKERS_PER_KEY, default 1, max 4)."""
    try:
        return min(4, max(1, int(os.environ.get("EJEE_APP_WORKERS_PER_KEY", "1"))))
    except ValueError:
        return 1


class Pool:
    """``workers_per_key()`` workers per Meta API key, all taking parts from the same ordered queue."""

    def __init__(self, runner=default_runner, publisher=remote.publish):
        self.runner, self.publisher = runner, publisher
        self.wake = threading.Event()
        self.stop_flag = threading.Event()
        self.workers: list[Pipeline] = []
        self._lock = threading.Lock()

    def ensure(self):
        """Start workers up to the number of saved keys (call after Settings change)."""
        with self._lock:
            want = max(1, len(store.meta_keys())) * workers_per_key()
            while len(self.workers) < want:
                w = Pipeline(self.runner, self.publisher, slot=len(self.workers), pool=self)
                w.wake, w.stop_flag = self.wake, self.stop_flag
                self.workers.append(w)
                w.start()

    start = ensure

    def active_count(self) -> int:
        return sum(1 for w in self.workers if not w.parked and w.key())

    def resume(self):
        for w in self.workers:
            w.parked = None
        store.set_queue(False)
        self.ensure()

    def pause(self, reason="Paused by you. The current steps finish first.", kind="user"):
        store.set_queue(True, reason, kind)

    def shutdown(self):
        self.stop_flag.set()
        self.wake.set()
        for w in self.workers:
            if w.proc and w.proc.poll() is None:
                w.proc.terminate()

    def running(self) -> dict:
        return {"jobs": [w.current for w in self.workers if w.current], "workers": len(self.workers),
                "active": self.active_count(), "parked": [w.parked for w in self.workers if w.parked]}


# ------------------------------------------------------------------ helpers
def _sha(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _bundle_name(run: Path) -> str:
    try:
        name = json.loads((run / "manifest.json").read_text(encoding="utf-8")).get("paper_name") or run.name
    except (OSError, ValueError):
        name = run.name
    safe = re.sub(r"[^\w\- .()]+", "_", name, flags=re.UNICODE).strip(" ._") or "bundle"
    return f"{safe}.plbundle"


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _progress_errors(run, stage) -> str:
    progress = _read_json(run / "progress.json")
    section = progress.get("questions" if stage == "extract" else "node3", {}) or {}
    return "\n".join(str(v.get("error") or v.get("errors") or "") for v in section.values()
                     if isinstance(v, dict) and not v.get("ok"))


def _failed_questions(run, stage) -> list[str]:
    progress = _read_json(run / "progress.json")
    section = progress.get("questions" if stage == "extract" else "node3", {}) or {}
    return sorted((k for k, v in section.items() if isinstance(v, dict) and not v.get("ok")),
                  key=lambda n: (len(n), n))


def copy_bundle(job: dict, bundle: Path) -> None:
    """Optional off-machine copy of every exported bundle.

    ``EJEE_APP_BUNDLE_COPY`` names a folder (e.g. one a sync client such as
    OneDrive uploads); bundles land in ``<folder>/<book>/``. A failed copy is
    recorded on the job but never fails the part.
    """
    target = os.environ.get("EJEE_APP_BUNDLE_COPY")
    if not target:
        return
    import shutil
    book = re.sub(r'[<>:"/\\|?*]+', "_", job["source"]).strip(" .") or job["slug"]
    dest = Path(target) / book / bundle.name
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".partial")
        shutil.copyfile(bundle, tmp)
        os.replace(tmp, dest)
    except OSError as exc:
        current = store.job(job["id"])["detail"] or {}
        store.update_job(job["id"], detail={**current, "copy_error": f"{dest}: {exc}"})


def _verify_errors(run) -> list[str]:
    return [str(e) for e in _read_json(run / "verification.json").get("errors", [])]


def _last_error(out: str) -> str:
    lines = [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
    for ln in reversed(lines):
        if re.search(r"Error|error|failed|refus|invalid", ln):
            return ln[:400]
    return (lines[-1][:400] if lines else "See the log.")


def _systemic_message(kind, stage) -> str:
    where = "question extraction" if stage == "extract" else "topic tagging"
    return {
        "meta": f"Paused at {where}: the Meta API key was rejected. Update it in Settings, then press Resume. "
                "Finished questions are kept and not billed again.",
        "rate": f"Paused at {where}: the model endpoint is rate-limiting or out of quota. Press Resume later.",
        "network": f"Paused at {where}: the model endpoint could not be reached. Check the internet connection, "
                   "then press Resume.",
    }[kind]


# ------------------------------------------------------------- direct mode
def _held_questions(run: Path, review_errors: list[str]) -> list[str]:
    """Question numbers whose holds are approved automatically (for the job list)."""
    held = set()
    folder = run / "review_required"
    if folder.is_dir():
        for f in folder.glob("*.json"):
            if not _read_json(f).get("approved"):
                held.add(f.stem)
    for e in review_errors:
        m = re.match(r"(?:Unresolved extraction review: )?(\d+)(?:/|\.json|:)", e)
        if m:
            held.add(m[1])
    return sorted(held, key=lambda n: (len(n), n))


def log_tail(job: dict, lines=200) -> str:
    log = run_dir(job["slug"], job["part"]).parent / f"part-{job['part']:03d}.log"
    if not log.is_file():
        return ""
    with open(log, "rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - 200_000))
        data = fh.read().decode("utf-8", "replace")
    return "\n".join(data.splitlines()[-lines:])
