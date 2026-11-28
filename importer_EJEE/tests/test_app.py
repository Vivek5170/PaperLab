"""EJEE Importer app: index, API guards, settings gate, cart, queue recovery
and the PaperLab upload client. Offline: synthetic EJEE database, isolated
data folder and run root, stub phases, and a fake PaperLab HTTP server."""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(ROOT))

H = {"x-ejee-app": "1"}


def _png(path, color):
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (200, 120), color).save(path)


def make_ejee(tmp: Path):
    """A tiny EJEE export: one textbook (17 grouped items -> 2 parts), an
    excluded institute source with study material + a test paper, and a
    teaching card."""
    db = tmp / "ejee.db"
    up = tmp / "uploads"
    c = sqlite3.connect(db)
    c.executescript("""
    CREATE TABLE resources (id INTEGER PRIMARY KEY, topic_id INTEGER, type TEXT, title TEXT, position INTEGER,
        file_name TEXT, file_orig TEXT, mime TEXT, question TEXT, answer TEXT, solution TEXT, difficulty TEXT,
        source TEXT, tags TEXT, exam TEXT, year TEXT, shift TEXT, qtype TEXT, created_at TEXT, grp TEXT, fav INTEGER,
        part TEXT, fingerprint TEXT, review TEXT, file_alt TEXT, enhanced INTEGER, print_meta TEXT, altered INTEGER,
        status TEXT, src_doc TEXT, worksheet_no TEXT, uid TEXT);
    CREATE TABLE nodes (id INTEGER PRIMARY KEY, parent_id INTEGER, level TEXT, name TEXT, position INTEGER,
        created_at TEXT, uid TEXT, code TEXT, description TEXT, boundary TEXT);
    CREATE TABLE resource_crops (id INTEGER PRIMARY KEY, resource_id INTEGER);
    CREATE TABLE resource_transcripts (id INTEGER PRIMARY KEY, resource_id INTEGER);
    INSERT INTO nodes (id, parent_id, level, name, position) VALUES (1, NULL, 'chapter', 'MECHANICS', 1),
        (2, 1, 'topic', 'Kinematics', 1), (3, NULL, 'chapter', 'OPTICS', 2);
    """)
    rid = 0
    meta = json.dumps({"box": [0.05, 0.05, 0.95, 0.95]})

    def add(**row):
        nonlocal rid
        rid += 1
        name = f"img/{rid}.png"
        _png(up / name, (240, 240, 240))
        row.setdefault("mime", "image/png")
        row.setdefault("print_meta", meta)
        row.update(id=rid, file_name=name)
        c.execute(f"INSERT INTO resources ({','.join(row)}) VALUES ({','.join('?' * len(row))})", tuple(row.values()))
        return rid

    for n in range(1, 18):
        add(source="Test Book", type="subjective", title=f"Test Book · 1.{n}", grp=f"tb-1.{n}", part="q", position=1,
            topic_id=2, difficulty="Easy", qtype="Subjective", question=f"A ball rolls {n} m.")
        if n % 2:
            add(source="Test Book", type="subjective", title=f"Test Book · 1.{n} sol", grp=f"tb-1.{n}", part="sol",
                position=1, topic_id=2)
    for n in range(1, 4):
        add(source="ALLEN", type="objective", title=f"Allen Revision Assignment · Q{n}", grp=f"ra-{n}", part="q",
            position=1, answer="(A)", exam="JEE Main", year="2024", topic_id=3)
        add(source="ALLEN", type="jadv", title=f"Allen Advanced Test 1 · Q{n}", grp=f"gta-{n}", part="q",
            position=1, answer="(B)", topic_id=3)
    add(source="Laws of motion slides", type="concept", title="Newton slides · 1", topic_id=2)
    # An EJEE row whose image file is missing: nobody can convert it.
    c.execute("INSERT INTO resources (id, source, type, title, grp, part, position, file_name, mime, print_meta) "
              "VALUES (999, 'Test Book', 'subjective', 'Test Book · 9.9', 'tb-9.9', 'q', 1, 'img/missing.png', "
              "'image/png', ?)", (meta,))
    c.commit()
    c.close()
    return db, up


@pytest.fixture()
def env(tmp_path, monkeypatch):
    runs_rel = f"runs/tmp-apptest-{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("EJEE_APP_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("EJEE_APP_RUNS", runs_rel)
    db, up = make_ejee(tmp_path)
    import ejee_index
    ejee_index.build(db, up)
    yield {"db": db, "uploads": up, "tmp": tmp_path, "runs": ROOT / runs_rel}
    shutil.rmtree(ROOT / runs_rel, ignore_errors=True)


# ------------------------------------------------------------------- index
def test_index_lists_every_question_of_every_source_as_convertible(env):
    import ejee_index
    facets = ejee_index.facets({}, {})
    cats = {f["value"]: f["count"] for f in facets["category"]}
    # Institute material and test papers are listed like any book; slides are not questions.
    assert cats == {"Textbook": 17, "Institute study material": 3, "Institute test papers": 3}
    book = ejee_index.search({"source": ["Test Book"]}, {}, limit=60)
    assert book["total"] == 17
    parts = sorted({(i["part"], i["localNo"]) for i in book["items"]})
    assert parts[0] == (1, 1) and parts[-1] == (2, 2)
    assert {i["answer"] for i in book["items"]} == {"solution", "none"}
    every = ejee_index.search({}, {}, limit=60)["items"]
    assert all(i["part"] and i["localNo"] for i in every) and "excluded" not in every[0]
    # The row with a missing image is not listed but counted, never silently lost.
    assert ejee_index.status()["unconvertible"] == 1
    # Topic filter covers the subtree; counts roll up to the chapter.
    assert ejee_index.search({"topic": ["1"]}, {})["total"] == 17
    assert facets["topicCounts"]["1"] == 17
    # Status filter uses cart/job state.
    assert ejee_index.search({"status": ["in_cart"]}, {(book["items"][0]["slug"], 1): "in_cart"})["total"] == 15
    assert ejee_index.search({"q": "rolls 1.13"}, {})["total"] == 1  # every word must match


# --------------------------------------------------------------- api guard
@pytest.fixture()
def client(env):
    from fastapi.testclient import TestClient
    import server
    with TestClient(server.app, base_url="http://127.0.0.1:8030") as c:
        yield c


def test_api_refuses_foreign_hosts_missing_header_and_cross_origin(client):
    assert client.get("/api/health").json()["ok"]
    assert client.get("/api/health", headers={"host": "evil.example"}).status_code == 421
    assert client.get("/api/health", headers={"host": "x.trycloudflare.com"}).status_code == 421  # no implicit tunnels
    assert client.post("/api/search", json={}).status_code == 403
    assert client.post("/api/search", json={}, headers={**H, "origin": "http://evil.example"}).status_code == 403


def test_public_host_is_explicit_opt_in(client, monkeypatch):
    monkeypatch.setenv("EJEE_APP_PUBLIC_HOSTS", "demo.example.org")
    assert client.get("/api/health", headers={"host": "demo.example.org"}).status_code == 200
    assert client.get("/api/health", headers={"host": "other.example.org"}).status_code == 421


def test_settings_hide_secrets_and_gate_processing(client, env):
    r = client.put("/api/settings", headers=H, json={
        "ejee_db": str(env["db"]), "uploads": str(env["uploads"]), "meta_api_key": "sk-abcdefgh1234"})
    body = r.json()
    assert r.status_code == 200 and body["meta_api_key_set"] and body["meta_api_key_hint"] == "…1234"
    assert "sk-abcdefgh1234" not in r.text and "meta_api_key" not in body
    missing = {m["key"] for m in client.get("/api/status").json()["missing"]}
    assert missing == {"server_url", "archivist_password"}
    assert client.put("/api/settings", headers=H, json={"server_url": "http://example.org"}).status_code == 422
    slug = client.post("/api/search", headers=H, json={"filters": {"source": ["Test Book"]}}).json()["items"][0]["slug"]
    assert client.post("/api/cart", headers=H, json={"slug": slug, "part": 1}).status_code == 200
    r = client.post("/api/process/start", headers=H)
    assert r.status_code == 400 and "Archivist password" in r.json()["detail"]["message"]
    assert len(client.get("/api/cart").json()["items"]) == 1  # nothing moved


def test_cart_freezes_plan_and_takes_institute_papers_directly(client, env):
    client.put("/api/settings", headers=H, json={"ejee_db": str(env["db"]), "uploads": str(env["uploads"])})
    allen = client.post("/api/search", headers=H, json={"filters": {"source": ["ALLEN"]}}).json()["items"][0]
    assert client.post("/api/cart", headers=H, json={"slug": allen["slug"], "part": 1}).status_code == 200
    book = client.post("/api/search", headers=H, json={"filters": {"source": ["Test Book"]}}).json()["items"][0]
    cart = client.post("/api/cart", headers=H, json={"slug": book["slug"], "part": 2}).json()
    assert cart["questions"] == 6 + 2  # ALLEN part 1 (6 items) + book part 2 (2 items)
    plan = json.loads((env["runs"] / book["slug"] / "plan.json").read_text(encoding="utf-8"))
    assert len(plan["parts"]) == 2 and len(plan["parts"][1]) == 2
    got = client.post("/api/search", headers=H, json={"filters": {"status": ["in_cart"]}}).json()
    assert got["total"] == 8


def test_convert_book_adds_remaining_parts_once(client, env):
    client.put("/api/settings", headers=H, json={"ejee_db": str(env["db"]), "uploads": str(env["uploads"])})
    books = client.post("/api/books", headers=H, json={}).json()["books"]
    assert [b["source"] for b in books] == ["Test Book", "ALLEN"]  # textbooks first; slides not listed
    book = books[0]
    assert book["parts"] == 2 and book["remaining"] == 2 and book["questions"] == 17
    assert client.post("/api/books/cart", headers=H, json={"slug": book["slug"], "parts": "3"}).status_code == 422
    r = client.post("/api/books/cart", headers=H, json={"slug": book["slug"], "parts": "2"}).json()
    assert r["added"] == [2] and r["questions"] == 2
    r = client.post("/api/books/cart", headers=H, json={"slug": book["slug"], "parts": "all"}).json()
    assert r["added"] == [1] and r["skipped"] == [2]
    again = client.post("/api/books", headers=H, json={"q": "test"}).json()["books"]
    assert again[0]["remaining"] == 0 and again[0]["counts"] == {"in_cart": 2}
    assert (env["runs"] / book["slug"] / "plan.json").is_file()


# ----------------------------------------------------------------- queue
def _job(env):
    import store
    import ejee_index
    item = ejee_index.search({"source": ["Test Book"]}, {})["items"][0]
    store.save_settings({"ejee_db": str(env["db"]), "uploads": str(env["uploads"]), "server_url": "https://pl.test"})
    store.save_secrets({"meta_api_key": "k" * 12, "archivist_password": "p" * 12})
    store.cart_add(item["slug"], item["source"], 1, 15)
    [job_id] = store.enqueue_cart()
    return job_id


def test_answered_only_trimmed_plan_is_never_recut(env, monkeypatch):
    """A trimmed plan's published parts must keep their numbering (no re-cut from part 1)."""
    import json as _json
    import pipeline
    import store
    job_id = _job(env)
    job = store.job(job_id)
    monkeypatch.setattr(pipeline, "answered_only", lambda source: True)
    book = env["runs"] / job["slug"]
    book.mkdir(parents=True, exist_ok=True)
    frozen = {"schema": 1, "source": job["source"], "part_size": 15, "parts": [["a"], ["b"]],
              "items": {}, "_trim": {"from_part": 2, "policy": "answered"}}
    (book / "plan.json").write_text(_json.dumps(frozen), encoding="utf-8")
    plan = pipeline.ensure_plan(job["source"], job["slug"], str(env["db"]), str(env["uploads"]))
    assert plan["parts"] == [["a"], ["b"]]
    assert _json.loads((book / "plan.json").read_text(encoding="utf-8")) == frozen
    # untrimmed plan of a started book: refuse rather than renumber published parts
    del frozen["_trim"]
    (book / "plan.json").write_text(_json.dumps(frozen), encoding="utf-8")
    store.update_job(job_id, status="done")
    with pytest.raises(ValueError, match="already started"):
        pipeline.ensure_plan(job["source"], job["slug"], str(env["db"]), str(env["uploads"]))


def test_silent_phase_is_killed_by_stall_guard(tmp_path, monkeypatch):
    """A child that hangs (e.g. a model request with no timeout) is killed, not waited on forever."""
    import os
    import time as _time
    import pipeline
    hang = tmp_path / "hang.py"
    hang.write_text("import time\nprint('Extracting 1', flush=True)\ntime.sleep(120)\n", encoding="utf-8")
    monkeypatch.setattr(pipeline, "IMPORTER", hang)
    monkeypatch.setenv("EJEE_APP_STALL_SEC", "1")
    log = tmp_path / "part.log"
    t0 = _time.monotonic()
    rc, _ = pipeline.default_runner("extract", tmp_path / "cfg.json", log, dict(os.environ))
    assert rc == pipeline.STALLED_RC
    assert _time.monotonic() - t0 < 30
    assert "stall guard" in log.read_text(encoding="utf-8")


def test_stalled_part_requeues_then_fails_without_pausing_queue(env):
    import pipeline
    import store
    job_id = _job(env)

    def runner(phase, cfg, log, e, args=(), on_proc=None):
        if phase == "prepare":
            Recorder()(phase, cfg, log, e, args, on_proc)
            return 0, ""
        return pipeline.STALLED_RC, ""

    worker = pipeline.Pipeline(runner=runner, publisher=lambda *a: {"papers": []})
    store.set_queue(False)
    for expected in ("queued", "queued", "failed"):
        worker.process(store.job(job_id))
        job = store.job(job_id)
        assert job["status"] == expected, job
        assert not store.queue_state()["paused"]
    assert job["detail"] == {"stalls": 3} and job["error_kind"] == "network"


class Recorder:
    """Stub importer phases: write the files the real ones would, on demand."""

    def __init__(self):
        self.calls = []
        self.fail = {}  # phase -> (rc, output) for the next call(s)

    def __call__(self, phase, cfg_path, log_path, env, args=(), on_proc=None):
        self.calls.append(phase)
        cfg = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
        run = ROOT / cfg["run_dir"]
        if phase in self.fail:
            rc, out = self.fail[phase].pop(0)
            if not self.fail[phase]:
                del self.fail[phase]
            return rc, out
        if phase == "prepare":
            (run / "manifest.json").write_text(json.dumps({"paper_name": "Test Book — Part 1", "items": []}))
        if phase == "export":
            Path(args[1]).write_bytes(b"PK fake bundle")
        return 0, f"{phase} ok"


def test_meta_failure_pauses_queue_and_resume_skips_finished_steps(env):
    import pipeline
    import store
    job_id = _job(env)
    runner, sent = Recorder(), []
    runner.fail["extract"] = [(2, "1: {'ok': False, 'error': 'AuthenticationError: 401 invalid api key'}")]
    worker = pipeline.Pipeline(runner=runner, publisher=lambda url, pw, b: sent.append(Path(b).read_bytes())
                               or {"papers": [{"archive_paper": 7, "questions": 15}], "already_imported": False})
    store.set_queue(False)
    worker.process(store.job(job_id))
    job, q = store.job(job_id), store.queue_state()
    assert q["paused"] and q["kind"] == "meta" and "Meta API key" in q["reason"]
    assert job["status"] == "queued" and job["stage"] == "extract" and job["done"] == ["prepare"]
    store.set_queue(False)
    worker.process(store.job(job_id))
    job = store.job(job_id)
    assert job["status"] == "done" and job["receipt"]["papers"][0]["archive_paper"] == 7
    assert runner.calls == ["prepare", "extract", "extract", "figures", "pack", "classify", "verify", "export"]
    assert sent == [b"PK fake bundle"]


def test_upload_failure_keeps_bundle_and_retries_same_bytes(env):
    import pipeline
    import remote
    import store
    job_id = _job(env)
    runner = Recorder()
    attempts = []

    def publisher(url, pw, bundle):
        attempts.append(Path(bundle).read_bytes())
        if len(attempts) == 1:
            raise remote.RemoteError("network", "Cannot reach https://pl.test: [Errno 11001] getaddrinfo failed")
        return {"papers": [], "already_imported": True}

    worker = pipeline.Pipeline(runner=runner, publisher=publisher)
    store.set_queue(False)
    worker.process(store.job(job_id))
    job, q = store.job(job_id), store.queue_state()
    assert q["paused"] and q["kind"] == "network" and job["stage"] == "upload" and "export" in job["done"]
    store.set_queue(False)
    worker.process(store.job(job_id))
    assert store.job(job_id)["status"] == "done"
    assert runner.calls.count("export") == 1 and attempts[0] == attempts[1]


def _verify_with(errors_first):
    """Runner whose first verify reports ``errors_first``; later verifies pass."""
    runner = Recorder()
    approvals = []

    def run(phase, cfg_path, log_path, env_, args=(), on_proc=None):
        if phase == "approve":
            runner.calls.append("approve")
            approvals.append(list(args))
            return 0, "Approved"
        if phase == "verify" and runner.calls.count("verify") == 0:
            runner.calls.append("verify")
            run_ = ROOT / json.loads(Path(cfg_path).read_text(encoding="utf-8"))["run_dir"]
            (run_ / "verification.json").write_text(json.dumps({"errors": errors_first}))
            return 1, "verify failed"
        return runner(phase, cfg_path, log_path, env_, args, on_proc)
    return run, runner, approvals


def test_review_holds_are_approved_automatically_and_labelled_as_unreviewed(env):
    import pipeline
    import store
    job_id = _job(env)
    run, runner, approvals = _verify_with([
        "Unresolved extraction review: 4.json: crop limit reached",
        "4/qfig1.png: crop edge review required; approve the reviewed current PNG hash explicitly"])
    worker = pipeline.Pipeline(runner=run, publisher=lambda *a: {"papers": []})
    store.set_queue(False)
    worker.process(store.job(job_id))
    job = store.job(job_id)
    assert job["status"] == "done" and job["detail"]["auto_approved"] == ["4"]
    assert approvals == [["--by", pipeline.AUTO_BY, "--note", pipeline.AUTO_NOTE]]
    assert "no human review" in pipeline.AUTO_BY
    assert runner.calls.count("verify") == 2 and runner.calls[-1] == "export"


def test_real_verification_problems_still_fail_the_part(env):
    import pipeline
    import store
    job_id = _job(env)
    run, runner, approvals = _verify_with(["7: question.tex has unbalanced $", "Unresolved extraction review: 4.json"])
    worker = pipeline.Pipeline(runner=run, publisher=lambda *a: {"papers": []})
    store.set_queue(False)
    worker.process(store.job(job_id))
    job = store.job(job_id)
    assert job["status"] == "failed" and "unbalanced" in job["error"] and not approvals


def test_content_failure_after_retry_fails_only_that_part(env):
    import pipeline
    import store
    job_id = _job(env)
    runner = Recorder()
    runner.fail["extract"] = [(2, "3: {'ok': False, 'error': 'ValueError: figure missing'}")] * 2
    worker = pipeline.Pipeline(runner=runner, publisher=lambda *a: {})
    store.set_queue(False)
    worker.process(store.job(job_id))
    job = store.job(job_id)
    assert job["status"] == "failed" and job["error_kind"] == "content" and not store.queue_state()["paused"]
    assert runner.calls.count("extract") == 2


def test_tagging_abstention_publishes_untagged_but_errors_still_fail(env):
    import pipeline
    import store
    job_id = _job(env)
    runner = Recorder()

    def classify_abstains(phase, cfg_path, log_path, env_, args=(), on_proc=None):
        if phase == "classify":
            runner.calls.append("classify")
            run_ = ROOT / json.loads(Path(cfg_path).read_text(encoding="utf-8"))["run_dir"]
            (run_ / "progress.json").write_text(json.dumps({"questions": {}, "node3": {
                "1": {"ok": True, "codes": ["PH01.01"], "difficulty": "Easy"},
                "2": {"ok": False, "codes": [], "errors": [], "difficulty": None,
                      "raw_reply": "TOPICS: NONE\nDIFFICULTY: NONE\nSUGGESTION: figure needed"}}}))
            return 2, "incomplete: ['2']"
        return runner(phase, cfg_path, log_path, env_, args, on_proc)

    worker = pipeline.Pipeline(runner=classify_abstains, publisher=lambda *a: {"papers": []})
    store.set_queue(False)
    worker.process(store.job(job_id))
    job = store.job(job_id)
    assert job["status"] == "done" and job["detail"]["untagged"] == ["2"]
    cfg = json.loads((pipeline.run_dir(job["slug"], 1).parent / "part-001.json").read_text(encoding="utf-8"))
    assert cfg["allow_untagged"] is True
    from importer import is_abstention
    assert not is_abstention({"ok": False, "errors": ["parse failed"], "raw_reply": "garbage"})
    # topic chosen but 'DIFFICULTY: NONE' (seen on SBT-2): publish untagged -> Tagging Inbox
    assert is_abstention({"ok": False, "errors": [], "codes": ["PH14.05"], "difficulty": None,
                          "raw_reply": "TOPICS: 104\nDIFFICULTY: NONE\nSUGGESTION: NONE"})
    assert not is_abstention({"ok": True, "errors": [], "codes": ["PH14.05"], "difficulty": "Medium",
                              "raw_reply": "TOPICS: 104\nDIFFICULTY: Medium"})


def test_stale_run_is_rebuilt_from_prepare_after_replan(env):
    """A re-planned book restarts the stale run folder at prepare, not mid-pipeline."""
    import pipeline
    import store
    job_id = _job(env)
    runner = Recorder()
    worker = pipeline.Pipeline(runner=runner, publisher=lambda *a: {"papers": []})
    store.set_queue(False)
    worker.process(store.job(job_id))
    assert store.job(job_id)["status"] == "done"
    phases = [c for c in runner.calls]
    assert phases.count("prepare") == 1 and phases.count("extract") == 1
    # Now the "plan" changes: stale manifest must trigger a clean rebuild, exactly once.
    second = pipeline.Pipeline(runner=runner, publisher=lambda *a: {"papers": []})
    store.set_queue(False)
    job = store.job(job_id)
    store.update_job(job_id, status="queued", done=["prepare"])
    orig = pipeline.Pipeline._manifest_matches_plan
    pipeline.Pipeline._manifest_matches_plan = lambda self, j, r, c: False
    try:
        second.process(store.job(job_id))
        calls = runner.calls
        # rebuild from the top: a fresh full pass [prepare..export] after the old one.
        # Bug shape would be an extract BEFORE the second prepare (mid-pipeline resume).
        first_old, first_new = calls.index("prepare"), calls.index("prepare", 1)
        assert calls[first_new - 1] == "export" and calls[first_new + 1] == "extract", calls
    finally:
        pipeline.Pipeline._manifest_matches_plan = orig


def test_bundles_are_copied_off_machine_and_books_queue_in_added_order(env, monkeypatch):
    import pipeline
    import store
    copy_dir = env["tmp"] / "OneDrive" / "PaperLab bundles"
    monkeypatch.setenv("EJEE_APP_BUNDLE_COPY", str(copy_dir))
    job_id = _job(env)  # "Test Book" part 1
    worker = pipeline.Pipeline(runner=Recorder(), publisher=lambda *a: {"papers": []})
    store.set_queue(False)
    worker.process(store.job(job_id))
    assert store.job(job_id)["status"] == "done"
    copied = list(copy_dir.rglob("*.plbundle"))
    assert len(copied) == 1 and copied[0].parent.name == "Test Book" and copied[0].read_bytes() == b"PK fake bundle"
    # Cart order = order added, not alphabetical (Z before A here).
    store.cart_add("zz-book", "Zeta Book", 1, 15)
    store.cart_add("aa-book", "Alpha Book", 1, 15)
    new = store.enqueue_cart()
    assert [store.job(i)["source"] for i in new] == ["Zeta Book", "Alpha Book"]


def test_os_kill_pauses_instead_of_failing_the_part(env):
    import pipeline
    import store
    job_id = _job(env)
    runner = Recorder()
    runner.fail["prepare"] = [(0xC000026B, "")]  # Windows logoff/shutdown killed the child
    worker = pipeline.Pipeline(runner=runner, publisher=lambda *a: {"papers": []})
    store.set_queue(False)
    worker.process(store.job(job_id))
    job, q = store.job(job_id), store.queue_state()
    assert job["status"] == "queued" and job["stage"] == "prepare" and q["paused"] and q["kind"] == "restart"
    assert pipeline.was_killed(-15) and not pipeline.was_killed(2) and not pipeline.was_killed(1)
    store.set_queue(False)
    worker.process(store.job(job_id))
    assert store.job(job_id)["status"] == "done"


def test_prepared_run_not_yet_recorded_is_resumed_not_failed(env, monkeypatch):
    """Restart right after prepare: the run is kept and the part continues (no 'already prepared' failure)."""
    import pipeline
    import store
    monkeypatch.setattr(pipeline.Pipeline, "_manifest_matches_plan", lambda self, j, r, c: True)
    job_id = _job(env)
    runner = Recorder()
    worker = pipeline.Pipeline(runner=runner, publisher=lambda *a: {"papers": []})
    store.set_queue(False)
    worker.process(store.job(job_id))
    assert store.job(job_id)["status"] == "done"
    run = pipeline.run_dir(store.job(job_id)["slug"], store.job(job_id)["part"])
    (run / "manifest.json").write_text(json.dumps({"paper_name": "Test Book — Part 1",
                                                   "items": [{"plan_key": "q1", "number": "1"}]}))
    store.update_job(job_id, status="queued", done=[], stage="prepare")  # 'done' lost by the restart
    runner.calls.clear()
    worker.process(store.job(job_id))
    assert "prepare" not in runner.calls and store.job(job_id)["status"] == "done", runner.calls


def test_oversize_bundle_fails_its_part_without_pausing_queue(env, monkeypatch):
    import pipeline
    import store
    job_id = _job(env)
    monkeypatch.setattr(pipeline, "MAX_UPLOAD_BYTES", 1)
    sent = []
    worker = pipeline.Pipeline(runner=Recorder(), publisher=lambda *a: sent.append(a) or {"papers": []})
    store.set_queue(False)
    worker.process(store.job(job_id))
    job = store.job(job_id)
    assert job["status"] == "failed" and job["error_kind"] == "content" and "upload limit" in job["error"]
    assert not sent and not store.queue_state()["paused"]


def test_two_workers_per_key_and_claims_never_double_up(env, monkeypatch):
    import threading as _th
    import pipeline
    import store
    _job(env)
    store.cart_add(store.jobs()[0]["slug"], "Test Book", 2, 2)
    store.enqueue_cart()
    store.save_secrets({"extra_meta_keys": ["key-b-1111"]})
    monkeypatch.setenv("EJEE_APP_WORKERS_PER_KEY", "2")
    pool = pipeline.Pool(runner=Recorder(), publisher=lambda *a: {"papers": []})
    with pool._lock:  # build workers without starting threads
        for s in range(len(store.meta_keys()) * pipeline.workers_per_key()):
            pool.workers.append(pipeline.Pipeline(slot=s, pool=pool))
    assert [w.key() for w in pool.workers] == ["k" * 12, "key-b-1111", "k" * 12, "key-b-1111"]
    # many threads claiming at once: each queued part is handed out exactly once
    got, lock = [], _th.Lock()

    def grab():
        j = store.claim_next_job()
        if j:
            with lock:
                got.append(j["id"])

    threads = [_th.Thread(target=grab) for _ in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(got) == len(set(got)) == len(store.jobs())


def test_parallel_keys_share_the_queue_and_a_bad_key_only_benches_itself(env):
    import time
    import pipeline
    import store
    _job(env)  # Test Book part 1 queued, primary key "kkkk..."
    store.cart_add(store.jobs()[0]["slug"], "Test Book", 2, 2)
    store.enqueue_cart()
    store.save_secrets({"extra_meta_keys": ["bad-key-0000", "good-key-1111"]})
    assert store.meta_keys() == ["k" * 12, "bad-key-0000", "good-key-1111"]
    base = Recorder()
    used = []

    def runner(phase, cfg_path, log_path, env_, args=(), on_proc=None):
        used.append((phase, env_["META_API_KEY"]))
        if phase == "extract" and env_["META_API_KEY"] == "bad-key-0000":
            return 2, "1: {'ok': False, 'error': 'AuthenticationError: 401 invalid api key'}"
        time.sleep(0.05)
        return base(phase, cfg_path, log_path, env_, args, on_proc)

    pool = pipeline.Pool(runner=runner, publisher=lambda *a: {"papers": []})
    store.set_queue(False)
    pool.start()
    try:
        deadline = time.time() + 30
        while time.time() < deadline and any(j["status"] != "done" for j in store.jobs()):
            time.sleep(0.2)
        jobs = store.jobs()
        assert [j["status"] for j in jobs] == ["done", "done"], [(j["status"], j["error"]) for j in jobs]
        assert not store.queue_state()["paused"]  # one bad key never stops the queue
        assert any("bad-key" in (w.parked or "") or w.slot == 1 and w.parked for w in pool.workers)
        assert pool.running()["workers"] == 3 and pool.active_count() == 2
        keys = {k for p, k in used if p == "extract"}
        assert "good-key-1111" in keys or "k" * 12 in keys
    finally:
        pool.shutdown()


def test_interrupted_job_is_requeued_paused_on_restart(env):
    import store
    job_id = _job(env)
    store.set_queue(False)
    store.update_job(job_id, status="running", stage="extract", done=["prepare"])
    assert store.recover_interrupted() == 1
    job = store.job(job_id)
    assert job["status"] == "queued" and job["done"] == ["prepare"] and store.queue_state()["paused"]


# ---------------------------------------------------------------- remote
class FakePaperLab(BaseHTTPRequestHandler):
    imported = set()

    def log_message(self, *a):
        pass

    def _send(self, code, body=None, headers=()):
        data = json.dumps(body).encode() if body is not None else b""
        self.send_response(code)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send(200, {"ok": True}) if self.path == "/api/health" else self._send(404, {"detail": "nope"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        if self.path == "/api/auth/login":
            if json.loads(body)["password"] != "right-password":
                return self._send(401, {"detail": "wrong password"})
            return self._send(204, None, [("Set-Cookie", "paperlab_session=abc; HttpOnly")])
        if self.path == "/api/auth/logout":
            return self._send(204)
        if self.path.startswith("/api/bundles/import"):
            if self.headers.get("Cookie") != "paperlab_session=abc":
                return self._send(401, {"detail": "login"})
            dry = "dry_run=true" in self.path
            if body in self.imported:
                return self._send(409, {"detail": "already published"}) if dry else \
                    self._send(200, {"already_imported": True, "papers": [{"archive_paper": 1, "questions": 15}]})
            if dry:
                return self._send(200, {"dry_run": True, "mergeable": True, "papers": []})
            self.imported.add(body)
            return self._send(201, {"already_imported": False, "papers": [{"archive_paper": 1, "questions": 15}],
                                    "warnings": []})
        self._send(404, {"detail": "nope"})


@pytest.fixture()
def fake_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakePaperLab)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_publish_is_idempotent_and_reports_wrong_password(fake_server, tmp_path):
    import remote
    bundle = tmp_path / "p.plbundle"
    bundle.write_bytes(b"bundle-bytes")
    first = remote.publish(fake_server, "right-password", bundle)
    again = remote.publish(fake_server, "right-password", bundle)  # lost reply: same bytes again
    assert first["http_status"] == 201 and not first["already_imported"]
    assert again["http_status"] == 200 and again["already_imported"] and again["preview"] is None
    with pytest.raises(remote.RemoteError) as exc:
        remote.publish(fake_server, "wrong-password", bundle)
    assert exc.value.kind == "auth"
    with pytest.raises(remote.RemoteError) as exc:
        remote.publish("http://127.0.0.1:9", "x", bundle)
    assert exc.value.kind == "network"
    with pytest.raises(remote.RemoteError):
        remote.normalize_url("http://paperlab.example.org")
