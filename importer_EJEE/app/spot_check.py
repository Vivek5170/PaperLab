"""Hourly random spot check of what the EJEE Importer app has published.

    python importer_EJEE/app/spot_check.py                 # one check now
    python importer_EJEE/app/spot_check.py --every 3600     # keep checking hourly

Picks random questions from parts finished since the previous check and
writes ``<out>/<UTC time>/report.md`` with automatic findings (PaperLab's
own TeX syntax rules, answer line, [UNREADABLE], figures, very short text,
per-part holds/untagged/cost) plus, for a person to compare side by side,
the original EJEE page(s) and a screenshot of how PaperLab renders the
question (needs Edge, Chrome or Chromium; skipped otherwise). A stall
alert is raised when no part finished in the last interval while the queue
was running. ``<out>/index.md`` keeps one line per check.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parent.parent))  # PaperLab root, for app.latex_syntax

import store  # noqa: E402
from pipeline import run_dir  # noqa: E402

BROWSERS = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "chromium", "chromium-browser", "google-chrome", "microsoft-edge"]


def browser():
    for b in BROWSERS:
        if os.path.isabs(b) and Path(b).is_file():
            return b
        if not os.path.isabs(b) and shutil.which(b):
            return shutil.which(b)
    return None


def syntax_errors(tex: str) -> list[str]:
    try:
        from app.latex_syntax import analyze
        errors, _ = analyze(tex)
        return [str(e) for e in errors]
    except Exception as exc:  # checker unavailable: say so, don't guess
        return [f"(syntax checker unavailable: {exc})"]


def check_question(qdir: Path) -> list[str]:
    problems = []
    q = (qdir / "question.tex").read_text(encoding="utf-8") if (qdir / "question.tex").is_file() else ""
    s = (qdir / "solution.tex").read_text(encoding="utf-8") if (qdir / "solution.tex").is_file() else ""
    if not q.strip():
        problems.append("question.tex missing or empty")
    elif len(re.sub(r"\\[a-zA-Z]+|[{}$\s]", "", q)) < 25:
        problems.append(f"question text very short ({len(q)} chars)")
    if not (qdir / "solution.tex").is_file():
        problems.append("solution.tex missing")
    elif not re.search(r"Answer|no_solution_found|No worked solution|No solution provided", s):
        problems.append("no answer line in solution.tex")
    for name, tex in (("question", q), ("solution", s)):
        problems += [f"{name}.tex: {e}" for e in syntax_errors(tex)[:5]]
        if "\\eqno" in tex:
            problems.append(f"{name}.tex: leftover \\eqno")
        n = tex.count("[UNREADABLE]")
        if n:
            problems.append(f"{name}.tex: {n} × [UNREADABLE]")
    from PIL import Image
    for ref in re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]*)\}", q + s):
        f = qdir / ref
        if not f.is_file():
            problems.append(f"figure {ref} referenced but missing")
            continue
        with Image.open(f) as im:
            if min(im.size) < 30:
                problems.append(f"figure {ref} is tiny {im.size}")
    return problems


def screenshot(url: str, out: Path, exe: str | None) -> bool:
    if not exe:
        return False
    profile = out.parent / ".browser-profile"
    try:
        subprocess.run([exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                        f"--user-data-dir={profile}", "--window-size=1100,1500", "--virtual-time-budget=12000",
                        f"--screenshot={out}", url], capture_output=True, timeout=90,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return False
    return out.is_file() and out.stat().st_size > 5000


def run_check(out_root: Path, per_check: int, viewer: str, interval: int) -> Path:
    out_root.mkdir(parents=True, exist_ok=True)
    state_file = out_root / "state.json"
    state = json.loads(state_file.read_text(encoding="utf-8-sig")) if state_file.is_file() else {"checked_jobs": [],
                                                                                               "done_count": None}
    jobs = store.jobs()
    done = [j for j in jobs if j["status"] == "done" and j["receipt"]]
    new = [j for j in done if j["id"] not in state["checked_jobs"]]
    stamp = time.strftime("%Y-%m-%dT%H%MZ", time.gmtime())
    folder = out_root / stamp
    folder.mkdir()
    q = store.queue_state()
    counts = {s: sum(1 for j in jobs if j["status"] == s) for s in ("done", "running", "queued", "failed")}
    alerts = []
    elapsed = time.time() - state.get("checked_at", time.time())
    if state["done_count"] is not None and counts["done"] == state["done_count"] and not q["paused"] \
            and counts["queued"] and elapsed >= 0.9 * interval:
        alerts.append(f"STALL: no part finished in the last {int(elapsed // 60)} min while the queue was running")
    state["checked_at"] = time.time()
    if q["paused"]:
        alerts.append(f"Queue paused ({q['kind']}): {q['reason']}")
    for j in jobs:
        if j["status"] == "failed" and j["id"] not in state.get("reported_failed", []):
            alerts.append(f"FAILED: {j['source']} Part {j['part']} at {j['stage']}: {(j['error'] or '')[:200]}")
    state.setdefault("reported_failed", []).extend(j["id"] for j in jobs if j["status"] == "failed")

    lines = [f"# Spot check {stamp}", "",
             f"Queue: {'paused' if q['paused'] else 'running'} · done {counts['done']} · running "
             f"{counts['running']} · queued {counts['queued']} · failed {counts['failed']} · "
             f"{len(new)} part(s) finished since the last check", ""]
    part_notes = []
    for j in new:
        d = j["detail"] or {}
        usd_q = (j["usd"] or 0) / max(1, j["questions"])
        notes = []
        if d.get("auto_approved"):
            notes.append(f"{len(d['auto_approved'])} held figure(s) published unreviewed (Q{', Q'.join(d['auto_approved'])})")
        if d.get("untagged"):
            notes.append(f"untagged Q{', Q'.join(d['untagged'])}")
        if usd_q > 0.015:
            notes.append(f"high cost ${usd_q:.4f}/question")
        if d.get("copy_error"):
            notes.append(f"OneDrive copy failed: {d['copy_error']}")
        part_notes.append(f"- {j['source']} Part {j['part']}: ${j['usd']:.4f}" + (f" — {'; '.join(notes)}" if notes else ""))
    if part_notes:
        lines += ["## Parts finished", "", *part_notes, ""]

    exe = browser()
    sample = []
    for j in random.sample(new, min(len(new), per_check)) if new else []:
        run = run_dir(j["slug"], j["part"])
        try:
            manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        item = random.choice(manifest["items"])
        sample.append((j, run, manifest, item))
    lines += ["## Sampled questions", ""] if sample else ["No new parts to sample.", ""]
    flagged = 0
    for n, (j, run, manifest, item) in enumerate(sample, 1):
        qn = str(item["number"])
        qdir = run / "Outputs" / str(manifest["paper_id"]) / qn
        problems = check_question(qdir)
        flagged += bool(problems)
        tag = f"{n:02d}"
        srcs = []
        for k, row in enumerate(item.get("question_rows", []) + item.get("solution_rows", [])):
            body = run / "sources" / f"{row['id']}-body.png"
            if body.is_file():
                dest = folder / f"{tag}-source-{k + 1}.png"
                shutil.copyfile(body, dest)
                srcs.append(dest.name)
        archive_paper = ((j["receipt"] or {}).get("papers") or [{}])[0].get("archive_paper")
        shot = f"{tag}-paperlab.png"
        rendered = bool(archive_paper) and screenshot(f"{viewer.rstrip('/')}/search/{archive_paper}/{qn}",
                                                      folder / shot, exe)
        lines += [f"### {tag}. {j['source']} — Part {j['part']}, Q{qn} ({item.get('source_number', '')})", "",
                  f"- Archive paper {archive_paper}, question {qn}",
                  "- Automatic checks: " + ("**" + "; ".join(problems) + "**" if problems else "all passed"),
                  f"- Original page(s): {', '.join(srcs) or 'not found'}",
                  f"- PaperLab rendering: {shot if rendered else 'not captured'}", ""]
    if alerts:
        lines[2:2] = ["## Alerts", "", *[f"- **{a}**" for a in alerts], ""]
    (folder / "report.md").write_text("\n".join(lines), encoding="utf-8")
    summary = (f"{stamp}: done {counts['done']}, +{len(new)} parts, {len(sample)} sampled, {flagged} flagged"
               + (f", ALERTS: {' | '.join(alerts)}" if alerts else ""))
    with open(out_root / "index.md", "a", encoding="utf-8") as fh:
        fh.write(f"- [{stamp}]({stamp}/report.md) {summary}\n")
    state["checked_jobs"] += [j["id"] for j in new]
    state["done_count"] = counts["done"]
    state_file.write_text(json.dumps(state), encoding="utf-8")
    print(summary, flush=True)
    return folder


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(store.data_dir() / "spot-checks"))
    ap.add_argument("--per-check", type=int, default=4, help="questions sampled per check")
    ap.add_argument("--viewer", default="http://127.0.0.1:8011", help="PaperLab URL that shows the published papers")
    ap.add_argument("--every", type=int, default=0, help="repeat every N seconds (0 = once)")
    args = ap.parse_args()
    if args.every:
        guard = socket.socket()  # one hourly checker at a time (launcher may run twice)
        try:
            guard.bind(("127.0.0.1", 8039))
        except OSError:
            print("spot check already running", flush=True)
            return
    while True:
        try:
            run_check(Path(args.out), args.per_check, args.viewer, args.every or 3600)
        except Exception as exc:
            print(f"spot check error: {type(exc).__name__}: {exc}", flush=True)
        if not args.every:
            return
        time.sleep(args.every)


if __name__ == "__main__":
    main()
