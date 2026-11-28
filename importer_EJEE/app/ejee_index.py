"""Searchable index of every question in the EJEE database (read-only source).

One row per question item, grouped exactly like the importer does it
(``book_plan.load_book``): a grouped question with its continuation and
solution pages counts once. Every source is included (textbooks, institute
material and test papers, past-year and exam papers, olympiads) and every
listed item is convertible. Teaching slides (``type='concept'``) are not
questions and are left out. Items EJEE cannot supply (missing image file,
no body box, orphan solution) cannot be converted by anyone; they are not
listed but are counted in ``unconvertible`` so nothing disappears silently.

Parts (15 questions) come from the frozen ``plan.json`` when one exists,
otherwise from the same ``cut_parts`` rule the planner would freeze, so the
part a user adds to the cart is the part that gets processed.

The index is a separate SQLite file in the app data folder. It is rebuilt
when the EJEE database changes (path, size or mtime).
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

from store import ROOT, data_dir, runs_rel

sys.path.insert(0, str(ROOT))
import book_plan  # noqa: E402

INDEX_VERSION = 4
PART_SIZE = 15

QTYPES = ("Single correct", "Multiple correct", "Integer type", "Numerical", "Paragraph",
          "Matrix match", "Passage – numerical", "Subjective", "Book problem (as printed)")
TYPE_EXAM = {"jmain": "JEE Main", "jadv": "JEE Advanced", "olympiad": "Olympiad"}
ALLEN_MATERIAL = {"ra", "allenadv", "allen", "allengr"}  # Revision Assignment, modules, Guided Revision

CATEGORIES = ["Textbook", "Institute study material", "Institute test papers", "Past-year questions",
              "Exam papers", "Olympiad"]

_state = {"building": False, "progress": 0, "total": 0, "error": None, "source": ""}
_build_lock = threading.Lock()


def index_path() -> Path:
    return data_dir() / "index.db"


def connect_ejee(path) -> sqlite3.Connection:
    conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def connect_index(write=False) -> sqlite3.Connection:
    path = index_path()
    if write:
        conn = sqlite3.connect(path, timeout=30)
    else:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _fingerprint(db_path, uploads) -> dict:
    st = Path(db_path).stat()
    return {"ejee_db": str(Path(db_path).resolve()), "uploads": str(Path(uploads).resolve()),
            "size": st.st_size, "mtime": int(st.st_mtime), "version": INDEX_VERSION}


def status(db_path=None, uploads=None) -> dict:
    out = dict(_state)
    out["built"] = False
    out["stale"] = False
    if index_path().is_file():
        try:
            with connect_index() as c:
                meta = json.loads(c.execute("SELECT value FROM meta WHERE key='fingerprint'").fetchone()[0])
                out["built"] = True
                out["built_at"] = c.execute("SELECT value FROM meta WHERE key='built_at'").fetchone()[0]
                out["items"] = c.execute("SELECT count(*) FROM items").fetchone()[0]
                out["sources"] = c.execute("SELECT count(*) FROM sources WHERE items > 0").fetchone()[0]
                out["unconvertible"] = c.execute("SELECT count(*) FROM unconvertible").fetchone()[0]
            if db_path and uploads and Path(db_path).is_file():
                out["stale"] = meta != _fingerprint(db_path, uploads)
        except (sqlite3.Error, TypeError, ValueError):
            out["built"] = False
    return out


# ---------------------------------------------------------------- categories
def category(source: str, grp: str | None, row_type: str | None) -> str:
    s = (source or "").strip()
    low = s.lower()
    if re.match(r"^allen( new)?$", low):
        prefix = re.sub(r"[-_ ]?\d.*$", "", (grp or "").lower())
        return "Institute study material" if prefix in ALLEN_MATERIAL else "Institute test papers"
    if re.match(r"^(sri chaitanya|fiitjee)", low) or "q.pap" in low:
        return "Institute test papers"
    if re.match(r"^jee advanced \d{4} paper", low):
        return "Exam papers"
    if "pyq" in low:
        return "Past-year questions"
    if re.search(r"olympiad|\bipho\b|\bapho\b|\beupho\b|\binpho\b|\bioqp\b|\busapho\b|\bn?bpho\b|f\s*=\s*ma|"
                 r"\bmipt\b|\bpho\.rs\b", low):
        return "Olympiad"
    if re.search(r"\bbiit\b|jee digital|jeenious|\binsp\b|aakash|\bsheets?\b|^\d+[a-z]?\b|^\d+\s", low):
        return "Institute study material"
    return "Textbook"


def _year(value):
    try:
        y = int(float(value))
    except (TypeError, ValueError):
        return None
    return str(y) if 1950 <= y <= time.gmtime().tm_year + 1 else None


def _qtype(row):
    if row["qtype"]:
        return row["qtype"]
    first = (row["tags"] or "").split(",")[0].strip()
    return first if first in QTYPES else None


def _collection(label: str) -> str:
    """'Allen Advanced Test 13-04-2025 Paper 2 · Q15' -> 'Allen Advanced Test 13-04-2025 Paper 2'."""
    parts = [p.strip() for p in (label or "").split("·")]
    return " · ".join(parts[:-1]) if len(parts) > 1 else ""


# --------------------------------------------------------------------- build
def build(db_path, uploads, part_size=PART_SIZE):
    """Rebuild the index (blocking). Use :func:`build_async` from the server."""
    db_path, uploads = str(Path(db_path).resolve()), str(Path(uploads).resolve())
    src = connect_ejee(db_path)
    src.execute("BEGIN")  # one consistent snapshot
    rows = {}
    for r in src.execute("SELECT id, source, type, title, grp, part, qtype, tags, difficulty, exam, year, "
                         "topic_id, substr(question, 1, 400) AS question FROM resources"):
        rows[r["id"]] = r
    sources = [r[0] for r in src.execute("SELECT source FROM resources WHERE source IS NOT NULL "
                                         "GROUP BY source ORDER BY source")]
    nodes = [dict(r) for r in src.execute("SELECT id, parent_id, level, name, position FROM nodes")]
    _state.update(total=len(sources), progress=0)
    tmp = index_path().with_suffix(".building.db")
    tmp.unlink(missing_ok=True)
    out = sqlite3.connect(tmp)
    out.executescript("""
    CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE sources (source TEXT PRIMARY KEY, slug TEXT, category TEXT, items INTEGER,
        unconvertible INTEGER, parts INTEGER, planned INTEGER);
    CREATE TABLE nodes (id INTEGER PRIMARY KEY, parent_id INTEGER, level TEXT, name TEXT, position INTEGER);
    CREATE TABLE items (id INTEGER PRIMARY KEY, key TEXT NOT NULL, source TEXT NOT NULL, slug TEXT NOT NULL,
        category TEXT, kind TEXT, label TEXT, collection TEXT, part INTEGER NOT NULL, local_no INTEGER NOT NULL,
        qtype TEXT, difficulty TEXT, exam TEXT, year TEXT, topic_id INTEGER, answer TEXT,
        q_ids TEXT, s_ids TEXT, thumb_id INTEGER, preview TEXT, sort INTEGER,
        UNIQUE (source, key));
    CREATE TABLE unconvertible (source TEXT, key TEXT, label TEXT, reason TEXT);
    """)
    out.executemany("INSERT INTO nodes VALUES (:id, :parent_id, :level, :name, :position)", nodes)
    runs = ROOT / runs_rel()
    for n, source in enumerate(sources, 1):
        _state.update(progress=n, source=source)
        slug = book_plan.slug(source)
        # load_book already leaves out teaching slides (type 'concept').
        items, _ignored = book_plan.load_book(src, source, uploads)
        plan_file = runs / slug / "plan.json"
        membership = {}
        planned = 0
        if plan_file.is_file():
            try:
                cand = json.loads(plan_file.read_text(encoding="utf-8"))
                if cand.get("source") == source:
                    if in_answered_only(source):
                        stale = [k for part in cand["parts"] for k in part if not (
                            cand["items"][k]["solution_ids"] or cand["items"][k]["has_key"])]
                        if not stale:
                            planned = 1
                            for p, keys in enumerate(cand["parts"], 1):
                                for i, key in enumerate(keys, 1):
                                    membership[key] = (p, i)
                    else:
                        planned = 1
                        for p, keys in enumerate(cand["parts"], 1):
                            for i, key in enumerate(keys, 1):
                                membership[key] = (p, i)
            except (OSError, ValueError, KeyError):
                membership, planned = {}, 0
        if not planned:
            answered = [it for it in items if it["solution_ids"] or it["has_key"]] \
                if in_answered_only(source) else items
            for p, part in enumerate(book_plan.cut_parts(answered, part_size), 1):
                for i, it in enumerate(part, 1):
                    membership[it["key"]] = (p, i)
        cats = Counter()
        batch, defects = [], []
        for order, it in enumerate(items):
            first = rows.get(it["question_ids"][0]) if it["question_ids"] else None
            if it["key"] not in membership or first is None:
                # EJEE cannot supply it (missing image, no body box, orphan
                # solution, or not in the frozen plan): counted, not listed.
                defects.append((source, it["key"], it["label"], it["blocked"] or "not in the frozen book plan"))
                continue
            cat = category(source, first["grp"], first["type"])
            cats[cat] += 1
            part, local = membership[it["key"]]
            answer = "solution" if it["solution_ids"] else ("key" if it["has_key"] else "none")
            exam = first["exam"] or TYPE_EXAM.get(first["type"])
            batch.append((it["key"], source, slug, cat, it["kind"], it["label"], _collection(it["label"]),
                          part, local, _qtype(first), first["difficulty"], exam, _year(first["year"]),
                          first["topic_id"], answer, json.dumps(it["question_ids"]), json.dumps(it["solution_ids"]),
                          it["question_ids"][0], (first["question"] or "").strip() or None, order))
        out.executemany("INSERT OR IGNORE INTO items (key, source, slug, category, kind, label, collection, part, "
                        "local_no, qtype, difficulty, exam, year, topic_id, answer, q_ids, s_ids, "
                        "thumb_id, preview, sort) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
        out.executemany("INSERT INTO unconvertible VALUES (?,?,?,?)", defects)
        out.execute("INSERT INTO sources VALUES (?,?,?,?,?,?,?)",
                    (source, slug, cats.most_common(1)[0][0] if cats else category(source, None, None),
                     len(batch), len(defects), len({m[0] for m in membership.values()}), planned))
    src.close()
    out.executescript("""
    CREATE INDEX items_source ON items(source, sort);
    CREATE INDEX items_part ON items(slug, part, local_no);
    CREATE INDEX items_cat ON items(category);
    CREATE INDEX items_topic ON items(topic_id);
    """)
    out.execute("INSERT INTO meta VALUES ('fingerprint', ?)", (json.dumps(_fingerprint(db_path, uploads)),))
    out.execute("INSERT INTO meta VALUES ('built_at', ?)", (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),))
    out.commit()
    out.close()
    tmp.replace(index_path())


def build_async(db_path, uploads) -> bool:
    if not _build_lock.acquire(blocking=False):
        return False

    def run():
        _state.update(building=True, error=None, progress=0, total=0, source="")
        try:
            build(db_path, uploads)
        except Exception as exc:  # surfaced in /api/status
            _state["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            _state.update(building=False, source="")
            _build_lock.release()

    threading.Thread(target=run, name="ejee-index", daemon=True).start()
    return True


def refresh_planned(source: str, slug: str, plan: dict):
    """After freezing a plan, make the index use its exact part membership."""
    with connect_index(write=True) as c:
        for p, keys in enumerate(plan["parts"], 1):
            c.executemany("UPDATE items SET part=?, local_no=? WHERE source=? AND key=?",
                          [(p, i, source, k) for i, k in enumerate(keys, 1)])
        c.execute("UPDATE sources SET planned=1, parts=? WHERE source=?", (len(plan["parts"]), source))


# -------------------------------------------------------------------- search
FILTER_KEYS = ("category", "source", "qtype", "difficulty", "exam", "year", "answer", "status", "topic")


def _where(filters: dict, statuses: dict, skip=None):
    clauses, args = [], []
    for key in ("category", "source", "qtype", "difficulty", "exam", "year", "answer"):
        if key == skip:
            continue
        values = [v for v in (filters.get(key) or []) if v]
        if values:
            nullable = "(unspecified)" in values
            values = [v for v in values if v != "(unspecified)"]
            parts = []
            if values:
                parts.append(f"{key} IN ({','.join('?' * len(values))})")
                args.extend(values)
            if nullable:
                parts.append(f"{key} IS NULL")
            clauses.append("(" + " OR ".join(parts) + ")")
    topics = [int(t) for t in (filters.get("topic") or []) if str(t).isdigit()]
    if topics and skip != "topic":
        clauses.append(f"topic_id IN (SELECT id FROM topic_sel)")
    q = (filters.get("q") or "").strip()
    if q:
        for word in q.split()[:6]:
            clauses.append("(label LIKE ? OR source LIKE ? OR preview LIKE ?)")
            args.extend([f"%{word}%"] * 3)
    wanted = [s for s in (filters.get("status") or []) if s]
    if wanted and skip != "status":
        if "not_started" in wanted:
            others = [s for s in wanted if s != "not_started"]
            clause = "(NOT EXISTS (SELECT 1 FROM part_status ps WHERE ps.slug=items.slug AND ps.part=items.part))"
            if others:
                clause = (f"({clause} OR EXISTS (SELECT 1 FROM part_status ps WHERE ps.slug=items.slug AND "
                          f"ps.part=items.part AND ps.status IN ({','.join('?' * len(others))})))")
                args.extend(others)
            clauses.append(clause)
        else:
            clauses.append(f"EXISTS (SELECT 1 FROM part_status ps WHERE ps.slug=items.slug AND ps.part=items.part "
                           f"AND ps.status IN ({','.join('?' * len(wanted))}))")
            args.extend(wanted)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", args


def _prepare(c, filters, statuses):
    c.execute("CREATE TEMP TABLE IF NOT EXISTS part_status (slug TEXT, part INTEGER, status TEXT)")
    c.execute("DELETE FROM part_status")
    c.executemany("INSERT INTO part_status VALUES (?,?,?)", [(s, p, st) for (s, p), st in statuses.items()])
    c.execute("CREATE TEMP TABLE IF NOT EXISTS topic_sel (id INTEGER PRIMARY KEY)")
    c.execute("DELETE FROM topic_sel")
    topics = [int(t) for t in (filters.get("topic") or []) if str(t).isdigit()]
    if topics:
        kids = defaultdict(list)
        for r in c.execute("SELECT id, parent_id FROM nodes"):
            kids[r["parent_id"]].append(r["id"])
        seen, stack = set(), list(topics)
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            stack.extend(kids.get(n, []))
        c.executemany("INSERT OR IGNORE INTO topic_sel VALUES (?)", [(n,) for n in seen])


def search(filters: dict, statuses: dict, cursor=0, limit=24) -> dict:
    with connect_index() as c:
        _prepare(c, filters, statuses)
        where, args = _where(filters, statuses)
        total = c.execute(f"SELECT count(*) FROM items{where}", args).fetchone()[0]
        rank = "CASE category " + " ".join(f"WHEN '{name}' THEN {i}" for i, name in enumerate(CATEGORIES)) + " END"
        rows = c.execute(f"SELECT * FROM items{where} ORDER BY {rank}, source COLLATE NOCASE, sort LIMIT ? OFFSET ?",
                         (*args, limit, cursor)).fetchall()
    items = [card(r, statuses) for r in rows]
    nxt = cursor + len(items)
    return {"items": items, "total": total, "nextCursor": nxt if nxt < total else None, "hasMore": nxt < total}


def card(r, statuses) -> dict:
    return {"key": r["key"], "source": r["source"], "slug": r["slug"], "category": r["category"],
            "kind": r["kind"], "label": r["label"], "collection": r["collection"], "part": r["part"],
            "localNo": r["local_no"], "qtype": r["qtype"], "difficulty": r["difficulty"], "exam": r["exam"],
            "year": r["year"], "answer": r["answer"], "thumb": r["thumb_id"], "preview": r["preview"],
            "status": statuses.get((r["slug"], r["part"]), "not_started"),
            "questionIds": json.loads(r["q_ids"]), "solutionIds": json.loads(r["s_ids"])}


def facets(filters: dict, statuses: dict) -> dict:
    out = {}
    with connect_index() as c:
        _prepare(c, filters, statuses)
        for key in ("category", "source", "qtype", "difficulty", "exam", "year", "answer"):
            where, args = _where(filters, statuses, skip=key)
            order = "value DESC" if key == "year" else "count DESC"
            out[key] = [{"value": r["value"] if r["value"] is not None else "(unspecified)", "count": r["count"]}
                        for r in c.execute(f"SELECT {key} AS value, count(*) AS count FROM items{where} "
                                           f"GROUP BY {key} ORDER BY {order}", args)]
        where, args = _where(filters, statuses, skip="status")
        counts = Counter()
        for r in c.execute(f"SELECT slug, part, count(*) n FROM items{where} GROUP BY slug, part", args):
            counts[statuses.get((r["slug"], r["part"]), "not_started")] += r["n"]
        out["status"] = [{"value": k, "count": v} for k, v in counts.most_common()]
        where, args = _where(filters, statuses, skip="topic")
        per_node = {r["topic_id"]: r["n"] for r in c.execute(
            f"SELECT topic_id, count(*) n FROM items{where} GROUP BY topic_id", args)}
        parent = {r["id"]: r["parent_id"] for r in c.execute("SELECT id, parent_id FROM nodes")}
    subtree = Counter()
    for node, n in per_node.items():
        seen = set()
        while node is not None and node not in seen:
            seen.add(node)
            subtree[node] += n
            node = parent.get(node)
    out["topicCounts"] = {str(k): v for k, v in subtree.items()}
    return out


def topics() -> list[dict]:
    with connect_index() as c:
        return [{"code": str(r["id"]), "name": r["name"], "level": r["level"],
                 "parent": str(r["parent_id"]) if r["parent_id"] is not None else None}
                for r in c.execute("SELECT * FROM nodes ORDER BY position, id")]


def item(key: str, source: str, statuses: dict) -> dict | None:
    with connect_index() as c:
        r = c.execute("SELECT * FROM items WHERE key=? AND source=?", (key, source)).fetchone()
        if r is None:
            return None
        out = card(r, statuses)
        out["partItems"] = [{"key": x["key"], "label": x["label"], "localNo": x["local_no"],
                             "thumb": x["thumb_id"], "answer": x["answer"]}
                            for x in c.execute("SELECT key, label, local_no, thumb_id, answer FROM items "
                                               "WHERE slug=? AND part=? ORDER BY local_no", (r["slug"], r["part"]))]
        src = c.execute("SELECT * FROM sources WHERE source=?", (source,)).fetchone()
        out["sourceInfo"] = dict(src) if src else None
        if r["topic_id"] is not None:
            chain, node = [], r["topic_id"]
            parent = {x["id"]: (x["parent_id"], x["name"]) for x in c.execute("SELECT id, parent_id, name FROM nodes")}
            seen = set()
            while node in parent and node not in seen:
                seen.add(node)
                chain.append(parent[node][1])
                node = parent[node][0]
            out["topicPath"] = list(reversed(chain))
    return out


def books(q: str, categories: list[str], statuses: dict) -> list[dict]:
    """One row per source (book, paper series, sheet set) with part progress."""
    by_slug = defaultdict(Counter)
    for (slug, _part), st in statuses.items():
        by_slug[slug][st] += 1
    with connect_index() as c:
        rows = c.execute(
            "SELECT s.*, (SELECT thumb_id FROM items i WHERE i.source = s.source ORDER BY sort LIMIT 1) AS thumb, "
            "(SELECT count(*) FROM items i WHERE i.source = s.source AND answer = 'solution') AS solution, "
            "(SELECT count(*) FROM items i WHERE i.source = s.source AND answer = 'key') AS keyonly "
            "FROM sources s WHERE items > 0").fetchall()
    words = [w.lower() for w in (q or "").split()]
    rank = {name: i for i, name in enumerate(CATEGORIES)}
    out = []
    for r in rows:
        if words and not all(w in r["source"].lower() for w in words):
            continue
        if categories and r["category"] not in categories:
            continue
        counts = dict(by_slug.get(r["slug"], {}))
        taken = sum(counts.values())
        out.append({"source": r["source"], "slug": r["slug"], "category": r["category"], "questions": r["items"],
                    "parts": r["parts"], "solution": r["solution"], "keyOnly": r["keyonly"], "thumb": r["thumb"],
                    "counts": counts, "remaining": max(0, r["parts"] - taken)})
    out.sort(key=lambda b: (rank.get(b["category"], 99), b["source"].lower()))
    return out


def source_by_slug(slug: str) -> dict | None:
    with connect_index() as c:
        r = c.execute("SELECT * FROM sources WHERE slug=?", (slug,)).fetchone()
    return dict(r) if r else None


# Books where question-only items are not convertible: parts contain only
# questions with a key or a worked solution (ATOMIC_WRITE keeps done parts).
ANSWERED_ONLY_SOURCES = ("Hibbeler Dynamics 14e", "Savchenko · Problems in Physics",
                            "Meriam & Kraige Dynamics 7e")


def in_answered_only(source: str) -> bool:
    """Hibbeler/Savchenko/Meriam exact names, plus every SBT source."""
    if source in ANSWERED_ONLY_SOURCES:
        return True
    low = (source or "").lower()
    return low == "sbtv1" or low.startswith("sbt ") or low.startswith("sbt-") or " sbt " in f" {low} "


ANSWERED_ONLY = ("Hibbeler Dynamics 14e", "Savchenko · Problems in Physics",
                 "Meriam & Kraige Dynamics 7e")


def part_info(slug: str, part: int) -> dict | None:
    with connect_index() as c:
        rows = c.execute("SELECT * FROM items WHERE slug=? AND part=? ORDER BY local_no", (slug, part)).fetchall()
        if not rows:
            return None
        src = c.execute("SELECT * FROM sources WHERE slug=?", (slug,)).fetchone()
    answers = Counter(r["answer"] for r in rows)
    return {"slug": slug, "source": rows[0]["source"], "part": part, "questions": len(rows),
            "category": rows[0]["category"],
            "parts": src["parts"] if src else None, "planned": bool(src["planned"]) if src else False,
            "keys": [r["key"] for r in rows], "first": rows[0]["label"], "last": rows[-1]["label"],
            "answers": dict(answers), "thumbs": [r["thumb_id"] for r in rows[:4]]}
