"""Node 3 runner: classify questions (difficulty + topics + suggestion).

Text-only LLM job. Input per question: question.tex + solution.tex plus
the numbered 296-subtopic reference list. Output: topic indices in
priority order, difficulty, optional suggestion -- written as src='auto'
rows (human picks are never touched).

Usage:
    python run_topics.py [paper_id] [question_number] [--limit N] [--refill]

Defaults: every question with no human topics and no auto topics yet.
--refill also redoes auto-tagged ones. Nothing here blocks extraction.
"""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

import config  # noqa: F401 -- must be first: pins env from config.yaml + .env
import database
import directory_manager
from llm import get_llm, invoke_with_retry

PROMPTS_DIR = Path(__file__).parent / "prompts"

# Politeness gap between consecutive LLM calls (seconds; env override).
# Sequential bulk runs (20+ questions/paper) stay far from per-minute
# rate limits, so invoke_with_retry's backoff stays a safety net that
# almost never fires instead of a routine event. Negligible next to
# the 3-15s each call already takes.
PACE_SEC = float(os.environ.get("TOPICS_PACE_SEC", "1.0"))

TOPICS_RE = re.compile(r"^TOPICS:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
DIFF_RE = re.compile(r"^DIFFICULTY:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
SUGG_RE = re.compile(r"^SUGGESTION:\s*(.+)$", re.IGNORECASE | re.MULTILINE)


def build_topic_list() -> list[tuple[int, str]]:
    """[(1-based number, 'Module › Chapter › ... › subtopic')] in seed order."""
    database.init_topics()
    conn = database.get_connection()
    try:
        rows = conn.execute(
            "SELECT code, parent, level, name FROM topics ORDER BY rowid"
        ).fetchall()
    finally:
        conn.close()
    by_code = {r["code"]: r for r in rows}
    out = []
    n = 0
    for r in rows:
        if r["level"] != "subtopic":
            continue
        n += 1
        parts, cur = [], r["code"]
        while cur is not None and cur in by_code:
            parts.append(by_code[cur]["name"])
            cur = by_code[cur]["parent"]
        out.append((n, " › ".join(reversed(parts))))
    return out


def topic_codes_by_number() -> dict[int, str]:
    """1-based number -> topic code (same order as build_topic_list)."""
    database.init_topics()
    conn = database.get_connection()
    try:
        codes = [r["code"] for r in conn.execute(
            "SELECT code FROM topics WHERE level = 'subtopic' ORDER BY rowid"
        ).fetchall()]
    finally:
        conn.close()
    return {i + 1: c for i, c in enumerate(codes)}


def parse_topics_output(text: str, n_topics: int) -> dict:
    """Parse the strict 3-line reply; each field validated independently.

    Returns {numbers: [...], difficulty: Easy|Medium|Hard|None,
    suggestion: str|None, errors: [...]}. Invalid fields degrade to
    empty/None with an error note -- nothing raises.
    """
    errors: list[str] = []
    numbers: list[int] = []
    m = TOPICS_RE.search(text or "")
    if m:
        raw = m.group(1).strip()
        if raw.upper() != "NONE":
            for tok in re.split(r"[,\s]+", raw):
                if not tok:
                    continue
                try:
                    v = int(tok)
                except ValueError:
                    errors.append(f"bad topic number {tok!r}")
                    continue
                if not 1 <= v <= n_topics:
                    errors.append(f"topic number {v} out of 1..{n_topics}")
                    continue
                if v not in numbers:
                    numbers.append(v)
            numbers = numbers[:3]
    else:
        errors.append("missing TOPICS line")
    difficulty = None
    m = DIFF_RE.search(text or "")
    if m:
        d = m.group(1).strip().capitalize()
        if d in database.DIFFICULTY_VALUES:
            difficulty = d
        elif d.upper() != "NONE":
            errors.append(f"bad difficulty {m.group(1).strip()!r}")
    else:
        errors.append("missing DIFFICULTY line")
    suggestion = None
    m = SUGG_RE.search(text or "")
    if m:
        s = m.group(1).strip()
        if s.upper() != "NONE" and s:
            suggestion = s
    else:
        errors.append("missing SUGGESTION line")
    if not numbers and suggestion is None:
        errors.append("no topics and no suggestion: nothing to store")
    return {"numbers": numbers, "difficulty": difficulty,
            "suggestion": suggestion, "errors": errors}


def classify_question(paper_id: int, question_number: str,
                      topic_lines: list[str] | None = None) -> dict:
    """Run the classifier for one question; write auto rows; return report."""
    from langchain_core.messages import HumanMessage, SystemMessage

    qdir = directory_manager.get_question_dir(paper_id, question_number)
    qtex = (qdir / "question.tex").read_text(encoding="utf-8") \
        if (qdir / "question.tex").is_file() else ""
    stex = (qdir / "solution.tex").read_text(encoding="utf-8") \
        if (qdir / "solution.tex").is_file() else ""
    if not qtex.strip():
        return {"ok": False, "error": "question.tex missing/empty"}
    if topic_lines is None:
        topic_lines = [f"Topic {n} — {path}"
                       for n, path in build_topic_list()]
    system = (PROMPTS_DIR / "topic_prompt.md").read_text(encoding="utf-8")
    messages = [
        SystemMessage(content=system),
        HumanMessage(content="REFERENCE SUBTOPICS (stable numbering):\n"
                     + "\n".join(topic_lines)),
        HumanMessage(content=f"QUESTION {question_number}:\n{qtex}\n\n"
                     f"SOLUTION:\n{stex}"),
    ]
    t0 = time.time()
    llm = get_llm()
    response = invoke_with_retry(llm, messages)
    elapsed = time.time() - t0
    text = getattr(response, "content", "") or ""
    parsed = parse_topics_output(text, len(topic_lines))
    usage = getattr(response, "usage_metadata", None) or {}
    in_det = usage.get("input_token_details", None) or {}
    out_det = usage.get("output_token_details", None) or {}
    database.log_token_usage(
        paper_id, "topics",
        input_tokens=usage.get("input_tokens", 0),
        cache_read=in_det.get("cache_read", 0),
        output_tokens=usage.get("output_tokens", 0),
        reasoning_tokens=out_det.get("reasoning", 0),
    )
    qid = database.get_question_id(paper_id, question_number)
    codes = [topic_codes_by_number()[v] for v in parsed["numbers"]]
    if codes:
        database.set_question_topics(qid, codes, src="auto")
    # Suggestion is write-only-when-spoken: auto never clears human text.
    # only_fill: a human difficulty grade is never overwritten.
    database.set_question_difficulty(
        paper_id, question_number, parsed["difficulty"],
        topic_suggestion=parsed["suggestion"], only_fill=True,
    )
    return {"ok": True, "numbers": parsed["numbers"], "codes": codes,
            "difficulty": parsed["difficulty"],
            "suggestion": parsed["suggestion"],
            "errors": parsed["errors"], "elapsed_sec": round(elapsed, 1)}


def targets(paper_id: int | None = None, refill: bool = False) -> list[tuple]:
    """[(paper_id, question_number)] needing classification.

    Skips questions with any human topics. Without --refill also skips
    questions that already have auto topics.
    """
    conn = database.get_connection()
    try:
        if paper_id is None:
            qs = conn.execute(
                "SELECT paper_id, question_number FROM questions "
                "ORDER BY paper_id, id").fetchall()
        else:
            qs = conn.execute(
                "SELECT paper_id, question_number FROM questions "
                "WHERE paper_id = ? ORDER BY id", (paper_id,)).fetchall()
        out = []
        for r in qs:
            qid = conn.execute(
                "SELECT id FROM questions WHERE paper_id = ? AND question_number = ?",
                (r["paper_id"], r["question_number"])).fetchone()["id"]
            links = conn.execute(
                "SELECT src FROM question_topics WHERE question_id = ?",
                (qid,)).fetchall()
            srcs = {x["src"] for x in links}
            if "human" in srcs:
                continue
            if links and not refill:
                continue
            out.append((r["paper_id"], r["question_number"]))
        return out
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    paper_id = None
    only_qn = None
    limit = None
    refill = "--refill" in args
    args = [a for a in args if a != "--refill"]
    nums = [a for a in args if a != "--limit" and not a.startswith("--")]
    if "--limit" in args:
        try:
            limit = int(args[args.index("--limit") + 1])
        except (IndexError, ValueError):
            print("usage: run_topics.py [paper_id] [question] [--limit N] [--refill]")
            return 1
    if len(nums) >= 1:
        try:
            paper_id = int(nums[0])
        except ValueError:
            print(f"paper_id must be an integer, got {nums[0]!r}")
            return 1
    if len(nums) >= 2:
        only_qn = nums[1]
    if paper_id is not None and database.get_paper(paper_id) is None:
        print(f"paper_id {paper_id} does not exist")
        return 1
    todo = targets(paper_id, refill)
    if only_qn is not None:
        todo = [(p, q) for p, q in todo if q == only_qn]
        if not todo:
            print(f"nothing to do for {only_qn} (human-tagged or unknown?)")
            return 1
    if limit is not None:
        todo = todo[:limit]
    print(f"Node 3: {len(todo)} question(s) to classify")
    if not todo:
        return 0
    topic_lines = [f"Topic {n} — {path}" for n, path in build_topic_list()]
    ok = errs = 0
    t0 = time.time()
    last_call = 0.0
    for p, q in todo:
        gap = PACE_SEC - (time.time() - last_call)
        if gap > 0:
            time.sleep(gap)
        try:
            rep = classify_question(p, q, topic_lines)
        except Exception as exc:  # one bad question never stops the batch
            print(f"  [{p}/{q}] FAILED: {type(exc).__name__}: {exc}")
            errs += 1
            last_call = time.time()
            continue
        if rep.get("ok"):
            ok += 1
            print(f"  [{p}/{q}] topics={rep['codes']} "
                  f"diff={rep['difficulty']} "
                  f"sugg={'yes' if rep['suggestion'] else 'no'} "
                  f"{rep['elapsed_sec']}s"
                  + (f" parse-notes={rep['errors']}" if rep["errors"] else ""))
        else:
            errs += 1
            print(f"  [{p}/{q}] SKIPPED: {rep.get('error')}")
        last_call = time.time()
    print(f"done: {ok} classified, {errs} failed/skipped, "
          f"{time.time() - t0:.0f}s total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
