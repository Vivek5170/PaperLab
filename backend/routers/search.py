"""Search questions: faceted filter + keyset pagination (public read).

Scale design (validated against a synthetic 20k-question DB, see report):
- Filtering is SQL WHERE over indexed columns; never loads question rows
  outside the requested page. Papers are few (hundreds even at 20k
  questions) so exam/institute/year reduce to a paper-id set in Python.
- Topic selection (any level, overlapping allowed) expands inside the DB
  via a recursive CTE over topics(parent); UNION dedupes, no Python-side
  IN list of hundreds of subtopics.
- Ordering is questions.id (unique, stable). The cursor binds the
  normalized filter state: a cursor minted under different filters is
  rejected so pages can neither overlap nor skip.
- Per-question enrichment (topics batch, preview text, thumbnail) is one
  topics query + filesystem reads for the page only -- no per-question
  DB round-trips (no N+1).
- Only questions from done papers are searchable (consistent with Archive).
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import time

from fastapi import APIRouter, HTTPException, Query, status

import database
import directory_manager
from backend.search_norm import (
    expand_canonical,
    group_institutes,
    suggest_merges,
)

router = APIRouter()

PAGE_DEFAULT = 24
PAGE_MAX = 100
PREVIEW_CHARS = 200
FACETS_TTL_SEC = 60.0

_YEAR_RE = re.compile(r"(19|20)\d{2}")

_FACETS_CACHE: dict = {"version": 0, "ts": 0.0, "payload": None}


def bump_search_version() -> None:
    """Invalidate cached facets after searchable metadata changes.

    Call from every API mutation that touches papers/questions/topics.
    Background pipeline writes (outside the API) are covered by the TTL
    backstop in get_facets.
    """
    _FACETS_CACHE["version"] += 1
    _FACETS_CACHE["payload"] = None


# ---------------------------------------------------------------- parsing

def parse_year(value: str | None) -> int | None:
    if not value:
        return None
    m = _YEAR_RE.search(str(value))
    return int(m.group(0)) if m else None


def _norm_list(values: list[str] | None) -> list[str]:
    seen = sorted({v for v in (values or []) if v != ""})
    return seen


def _fingerprint(filters: dict) -> str:
    canon = {k: (sorted(v) if isinstance(v, list) else v)
             for k, v in filters.items()}
    return hashlib.sha256(
        json.dumps(canon, sort_keys=True).encode()).hexdigest()[:32]


def _encode_cursor(last_id: int, fingerprint: str) -> str:
    raw = json.dumps({"last": last_id, "f": fingerprint}).encode()
    return base64.urlsafe_b64encode(raw).decode()


def _decode_cursor(cursor: str) -> dict:
    try:
        return json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "bad cursor -- restart from the first page") from exc


# ---------------------------------------------------------------- snapshots

def _papers_snapshot(conn) -> list[dict]:
    """All papers (few hundred rows even at 20k questions): id, exam, raws, year."""
    return [
        {"id": r["id"], "title": r["paper_name"], "exam": r["exam_type"],
         "institute": r["source_institute"], "year": parse_year(r["paper_date"]),
         "status": r["status"] or "uploaded"}
        for r in conn.execute(
            "SELECT id, paper_name, exam_type, source_institute,"
            " paper_date, status FROM papers").fetchall()
    ]


def _institute_groups(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT p.source_institute AS name, COUNT(q.id) AS c"
        " FROM papers p LEFT JOIN questions q ON q.paper_id = p.id"
        " WHERE (p.status = 'done') GROUP BY p.source_institute").fetchall()
    return group_institutes([(r["name"], r["c"]) for r in rows])


def _topics_map(conn) -> dict[str, dict]:
    return {r["code"]: {"parent": r["parent"], "level": r["level"], "name": r["name"]}
            for r in conn.execute(
                "SELECT code, parent, level, name FROM topics").fetchall()}


def _chapter_of(code: str, tmap: dict) -> str | None:
    node = tmap.get(code)
    while node is not None:
        if node["level"] == "chapter":
            return node["name"]
        node = tmap.get(node["parent"]) if node["parent"] else None
    return None


# ---------------------------------------------------------------- facets

def _build_facets() -> dict:
    conn = database.get_connection()
    try:
        qtypes = [(r["qtype"] or "unknown", r["c"]) for r in conn.execute(
            "SELECT q.qtype, COUNT(*) AS c FROM questions q"
            " JOIN papers p ON p.id = q.paper_id"
            " WHERE p.status = 'done' GROUP BY q.qtype").fetchall()]
        diffs = [(r["difficulty"], r["c"]) for r in conn.execute(
            "SELECT q.difficulty, COUNT(*) AS c FROM questions q"
            " JOIN papers p ON p.id = q.paper_id"
            " WHERE p.status = 'done' GROUP BY q.difficulty").fetchall()]
        per_paper = [(r["paper_id"], r["c"]) for r in conn.execute(
            "SELECT q.paper_id, COUNT(*) AS c FROM questions q"
            " JOIN papers p ON p.id = q.paper_id"
            " WHERE p.status = 'done' GROUP BY q.paper_id").fetchall()]
        topic_counts = {r["topic_code"]: r["c"] for r in conn.execute(
            "SELECT qt.topic_code, COUNT(DISTINCT qt.question_id) AS c"
            " FROM question_topics qt JOIN questions q ON q.id = qt.question_id"
            " JOIN papers p ON p.id = q.paper_id"
            " WHERE p.status = 'done' GROUP BY qt.topic_code").fetchall()}
        # Distinct-question counts per subtree root (any level): a question
        # with two tags under one module counts once. The recursive CTE
        # walks topics(parent) down from every node; UNION dedupes.
        subtree_counts = {r["node"]: r["c"] for r in conn.execute(
            "WITH RECURSIVE d(root, code) AS ("
            " SELECT code, code FROM topics"
            " UNION"
            " SELECT d.root, t.code FROM topics t"
            " JOIN d ON t.parent = d.code)"
            " SELECT d.root AS node, COUNT(DISTINCT qt.question_id) AS c"
            " FROM d JOIN question_topics qt ON qt.topic_code = d.code"
            " JOIN questions q ON q.id = qt.question_id"
            " JOIN papers p ON p.id = q.paper_id"
            " WHERE p.status = 'done' GROUP BY d.root").fetchall()}
        papers = _papers_snapshot(conn)
        institutes = _institute_groups(conn)
    finally:
        conn.close()
    papers = [p for p in papers if p["status"] == "done"]
    by_paper_n = dict(per_paper)
    exams: dict[str, int] = {}
    years: dict[int, int] = {}
    for p in papers:
        n = by_paper_n.get(p["id"], 0)
        exams[p["exam"] or "Unknown"] = exams.get(p["exam"] or "Unknown", 0) + n
        if p["year"] is not None:
            years[p["year"]] = years.get(p["year"], 0) + n
    ungraded = next((c for d, c in diffs if d is None), 0)
    return {
        "qtypes": [{"value": v, "count": c} for v, c in sorted(qtypes)],
        "difficulties": [{"value": d, "count": c} for d, c in sorted(
            (x for x in diffs if x[0] is not None), key=lambda x: x[0])],
        "ungradedDifficulty": ungraded,
        "exams": [{"value": v, "count": c}
                  for v, c in sorted(exams.items(), key=lambda kv: kv[0] or "")],
        "institutes": institutes,
        "instituteSuggestions": suggest_merges(institutes),
        "years": [{"value": y, "count": c} for y, c in sorted(years.items())],
        "topicCounts": topic_counts,
        "topicSubtreeCounts": subtree_counts,
    }


@router.get("/facets")
def get_facets():
    """Filter metadata with per-value question counts (cached + versioned)."""
    now = time.monotonic()
    if (_FACETS_CACHE["payload"] is None
            or now - _FACETS_CACHE["ts"] > FACETS_TTL_SEC):
        _FACETS_CACHE["payload"] = _build_facets()
        _FACETS_CACHE["ts"] = now
    return {"version": _FACETS_CACHE["version"], **_FACETS_CACHE["payload"]}


# ---------------------------------------------------------------- preview

_TEX_SUBS = [
    (re.compile(r"%[^\n]*"), ""),                      # comments
    (re.compile(r"\\includegraphics(\[[^\]]*\])?\{[^}]*\}"), ""),  # figures
    (re.compile(r"\\begin\{[^}]*\}"), " "),
    (re.compile(r"\\end\{[^}]*\}"), " "),
]

_CMD_ARG_RE = re.compile(r"\\[a-zA-Z]+\{([^{}]*)\}")
_CMD_RE = re.compile(r"\\[a-zA-Z]+\s*")
_MATH_RE = re.compile(r"\$\$?(.*?)\$\$?", re.DOTALL)


def preview_text(tex: str, limit: int = PREVIEW_CHARS) -> str:
    """Flatten question TeX to a plain-text snippet (no KaTeX per card)."""
    s = re.sub(r"^\s*\d+\.\s*", "", tex or "")
    for rx, rep in _TEX_SUBS:
        s = rx.sub(rep, s)
    s = _MATH_RE.sub(lambda m: f" {m.group(1)} ", s)
    s = s.replace("\\(", " ").replace("\\)", " ")
    s = s.replace("\\[", " ").replace("\\]", " ")
    prev = None
    while prev != s:  # unwrap nested \cmd{...} -> inner text
        prev = s
        s = _CMD_ARG_RE.sub(lambda m: m.group(1), s)
    s = _CMD_RE.sub(" ", s)
    s = s.replace("{", " ").replace("}", " ").replace("$", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit] + ("…" if len(s) > limit else "")


def _thumb_url(paper_id: int, qn: str) -> str | None:
    """First question-side figure via existing storage conventions.

    Reuses app.figures.list_figures (trash/underscore + extension rules)
    and directory_manager.get_question_dir; only runs for questions on
    the current page -- never a tree scan.
    """
    from app.figures import figure_side, list_figures

    try:
        figs = list_figures(directory_manager.get_question_dir(paper_id, qn))
    except OSError:
        return None
    if not figs:
        return None
    first = next((p for p in figs if figure_side(p.name) == "question"), figs[0])
    return f"/api/papers/{paper_id}/questions/{qn}/figures/{first.name}"


# ---------------------------------------------------------------- search

def _filtered_paper_ids(papers: list[dict], exams: list[str], inst_raws: list[str],
                        years: list[int]) -> set[int] | None:
    if not exams and not inst_raws and not years:
        return None
    out = set()
    for p in papers:
        if exams and (p["exam"] or "Unknown") not in exams:
            continue
        if inst_raws and (p["institute"] or "Unknown") not in inst_raws:
            continue
        if years and p["year"] not in years:
            continue
        out.add(p["id"])
    return out


@router.get("")
def search_questions(
    qtype: list[str] = Query(default=[]),
    difficulty: list[str] = Query(default=[]),
    exam: list[str] = Query(default=[]),
    institute: list[str] = Query(default=[]),
    year: list[int] = Query(default=[]),
    topic: list[str] = Query(default=[]),
    limit: int = Query(default=PAGE_DEFAULT, ge=1, le=PAGE_MAX),
    cursor: str | None = None,
):
    qtypes = _norm_list(qtype)
    diffs = _norm_list(difficulty)
    exams = _norm_list(exam)
    inst_names = _norm_list(institute)
    years = sorted(set(year or []))
    topics = _norm_list(topic)

    bad_q = [v for v in qtypes if v not in database.QTYPE_VALUES]
    if bad_q:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"bad qtype {bad_q}: must be one of"
                            f" {', '.join(database.QTYPE_VALUES)}")
    bad_d = [v for v in diffs if v not in database.DIFFICULTY_VALUES]
    if bad_d:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"bad difficulty {bad_d}: must be one of"
                            f" {', '.join(database.DIFFICULTY_VALUES)}")

    filters = {"qtype": qtypes, "difficulty": diffs, "exam": exams,
               "institute": inst_names, "year": years, "topic": topics,
               "limit": limit}
    fp = _fingerprint(filters)
    last_id = 0
    if cursor:
        c = _decode_cursor(cursor)
        if c.get("f") != fp or not isinstance(c.get("last"), int):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "filters changed -- discard the cursor and restart from"
                " the first page")
        last_id = c["last"]

    conn = database.get_connection()
    try:
        papers = [p for p in _papers_snapshot(conn) if p["status"] == "done"]
        groups = _institute_groups(conn)
        try:
            inst_raws = expand_canonical(inst_names, groups) if inst_names else []
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
        paper_ids = _filtered_paper_ids(papers, exams, inst_raws, years)
        if paper_ids is not None and not paper_ids:
            return {"items": [], "total": 0, "nextCursor": None, "hasMore": False,
                    "filters": filters}
        by_paper = {p["id"]: p for p in papers}
        tmap = _topics_map(conn)
        if topics:
            known = set(tmap)
            bad_t = [t for t in topics if t not in known]
            if bad_t:
                raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                    f"unknown topic {bad_t}")

        where = ["p.status = 'done'"]
        cursor_where = "q.id > :last"
        params: dict = {"last": last_id}
        if topics:
            where.append(
                "EXISTS (SELECT 1 FROM question_topics qt"
                " JOIN (WITH RECURSIVE"
                " sel(code) AS (SELECT value FROM json_each(:topics)),"
                " d(code) AS (SELECT code FROM sel"
                " UNION SELECT t.code FROM topics t"
                " JOIN d ON t.parent = d.code)"
                " SELECT code FROM d) dd ON dd.code = qt.topic_code"
                " WHERE qt.question_id = q.id)")
            params["topics"] = json.dumps(topics)
        if qtypes:
            where.append("q.qtype IN (%s)" % ",".join(
                f":qt{i}" for i in range(len(qtypes))))
            params.update({f"qt{i}": v for i, v in enumerate(qtypes)})
        if diffs:
            where.append("q.difficulty IN (%s)" % ",".join(
                f":df{i}" for i in range(len(diffs))))
            params.update({f"df{i}": v for i, v in enumerate(diffs)})
        if paper_ids is not None:
            ids = sorted(paper_ids)
            where.append("q.paper_id IN (%s)" % ",".join(
                f":pp{i}" for i in range(len(ids))))
            params.update({f"pp{i}": v for i, v in enumerate(ids)})
        where_sql = " AND ".join(where)
        page_sql = f"{where_sql} AND {cursor_where}"

        rows = conn.execute(
            "SELECT DISTINCT q.id, q.paper_id, q.question_number, q.qtype,"
            " q.difficulty FROM questions q JOIN papers p ON p.id = q.paper_id"
            f" WHERE {page_sql} ORDER BY q.id LIMIT :lim",
            {**params, "lim": limit + 1}).fetchall()
        total = conn.execute(
            "SELECT COUNT(DISTINCT q.id) AS c FROM questions q"
            " JOIN papers p ON p.id = q.paper_id"
            f" WHERE {where_sql}", params).fetchone()["c"]

        has_more = len(rows) > limit
        page = rows[:limit]
        qids = [r["id"] for r in page]
        links: dict[int, list] = {qid: [] for qid in qids}
        if qids:
            ph = ",".join("?" for _ in qids)
            for r in conn.execute(
                    "SELECT question_id, topic_code, rank FROM question_topics"
                    f" WHERE question_id IN ({ph})"
                    " ORDER BY question_id, rank, topic_code", qids).fetchall():
                links[r["question_id"]].append(r["topic_code"])
    finally:
        conn.close()

    items = []
    for r in page:
        p = by_paper.get(r["paper_id"], {})
        codes = links.get(r["id"], [])
        chapters: list[str] = []
        for c in codes:
            ch = _chapter_of(c, tmap)
            if ch and ch not in chapters:
                chapters.append(ch)
        try:
            qdir = directory_manager.get_question_dir(r["paper_id"],
                                                      r["question_number"])
            tex = (qdir / "question.tex").read_text(encoding="utf-8")
        except OSError:
            tex = ""
        items.append({
            "paperId": r["paper_id"],
            "number": r["question_number"],
            "qtype": r["qtype"] or "unknown",
            "difficulty": r["difficulty"],
            "paper": {"title": p.get("title"), "exam": p.get("exam"),
                      "institute": p.get("institute"), "year": p.get("year")},
            "chapters": chapters[:2],
            "chapterOverflow": max(0, len(chapters) - 2),
            "topics": [{"code": c, "name": tmap[c]["name"]} for c in codes
                       if c in tmap],
            "preview": preview_text(tex),
            "thumb": _thumb_url(r["paper_id"], r["question_number"]),
        })
    next_cursor = (_encode_cursor(page[-1]["id"], fp)
                   if has_more and page else None)
    return {"items": items, "total": total, "nextCursor": next_cursor,
            "hasMore": has_more, "filters": filters}
