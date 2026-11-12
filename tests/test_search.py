"""Step 1 acceptance tests: /api/search + /api/search/facets (backend only).

Covers the approved safeguards: institute normalization (exact-match
auto-merge, alias map, suggestion-only fuzzy), cursor bound to filters,
recursive topic CTE (overlap/dedupe/any level), facet invalidation,
deterministic ordering, migration-safe indexes, no N+1.
"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

import database
import directory_manager


def _seed(client_db):
    """Deterministic fixture: 3 done papers + 1 indexing, 8 questions."""
    database.init_topics()
    dummy = client_db.parent / "dummy.pdf"
    dummy.write_bytes(b"%PDF-1.4\n%EOF")
    conn = database.get_connection()
    try:
        p1 = conn.execute(
            "INSERT INTO papers (paper_name, exam_type, paper_date,"
            " source_institute, status, question_pdf_path) VALUES (?,?,?,?,?,?)",
            ("Paper A", "JEE Advanced", "2025-09-07",
             "Sri Chaitanya IIT Academy", "done", str(dummy))).lastrowid
        p2 = conn.execute(
            "INSERT INTO papers (paper_name, exam_type, paper_date,"
            " source_institute, status, question_pdf_path) VALUES (?,?,?,?,?,?)",
            ("Paper B", "JEE Main", "18-10-2026",
             "BHASHYAM IIT-JEE ACADEMY", "done", str(dummy))).lastrowid
        p3 = conn.execute(
            "INSERT INTO papers (paper_name, exam_type, paper_date,"
            " source_institute, status, question_pdf_path) VALUES (?,?,?,?,?,?)",
            ("Paper C", "JEE Main", "2024-04-21",
             "Bhashyam IIT-JEE Academy", "done", str(dummy))).lastrowid
        p4 = conn.execute(
            "INSERT INTO papers (paper_name, exam_type, paper_date,"
            " source_institute, status, question_pdf_path) VALUES (?,?,?,?,?,?)",
            ("Paper D", "JEE Advanced", "2023-12-10",
             "FIITJEE", "indexing", str(dummy))).lastrowid
        qs = [
            # (paper, number, qtype, difficulty)
            (p1, "1", "scq", "Easy"),
            (p1, "2", "msq", "Medium"),
            (p1, "3", "int", None),
            (p2, "1", "scq", None),
            (p2, "2", "num", "Hard"),
            (p3, "1", "scq", "Easy"),
            (p3, "2", "mtx", None),
            (p4, "1", "scq", "Easy"),  # indexing paper: must never surface
        ]
        qids = {}
        for paper, num, qt, diff in qs:
            qid = conn.execute(
                "INSERT INTO questions (paper_id, question_number, qtype,"
                " difficulty, status) VALUES (?,?,?,?,?)",
                (paper, num, qt, diff, "draft")).lastrowid
            qids[(paper, num)] = qid
        # Tags: PH01.01 + PH01.02 (both under PH01-W1/PH01/M1),
        # PH13.14 (under M2).
        conn.execute(
            "INSERT INTO question_topics (question_id, topic_code, rank, src)"
            " VALUES (?,?,0,'human')", (qids[(p1, "1")], "PH01.01"))
        conn.execute(
            "INSERT INTO question_topics (question_id, topic_code, rank, src)"
            " VALUES (?,?,1,'human')", (qids[(p1, "1")], "PH01.02"))
        conn.execute(
            "INSERT INTO question_topics (question_id, topic_code, rank, src)"
            " VALUES (?,?,0,'human')", (qids[(p1, "2")], "PH01.02"))
        conn.execute(
            "INSERT INTO question_topics (question_id, topic_code, rank, src)"
            " VALUES (?,?,0,'human')", (qids[(p1, "2")], "PH13.14"))
        conn.execute(
            "INSERT INTO question_topics (question_id, topic_code, rank, src)"
            " VALUES (?,?,0,'human')", (qids[(p2, "2")], "PH01.01"))
        conn.commit()
        return {"p1": p1, "p2": p2, "p3": p3, "p4": p4}
    finally:
        conn.close()


@pytest.fixture()
def search_client(tmp_db, tmp_outputs, monkeypatch):
    ids = _seed(tmp_db)
    # Minimal question.tex files + one figure for preview/thumb paths.
    for paper, num in [(ids["p1"], "1"), (ids["p1"], "2"),
                       (ids["p2"], "2"), (ids["p3"], "1")]:
        qdir = directory_manager.get_question_dir(paper, num)
        (qdir / "figures").mkdir(parents=True, exist_ok=True)
        (qdir / "question.tex").write_text(
            f"{num}. Find $x^2$ for \\textbf{{body}} $m$.", encoding="utf-8")
    figdir = directory_manager.get_question_dir(ids["p1"], "1") / "figures"
    (figdir / "qfig1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    from backend.main import app
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, ids


def _get(client, path):
    r = client.get(path)
    assert r.status_code == 200, (path, r.status_code, r.text[:300])
    return r.json()


# ---------------------------------------------------------------- facets

def test_facets_counts_and_bhashyam_merge(search_client):
    client, _ = search_client
    f = _get(client, "/api/search/facets")
    qt = {x["value"]: x["count"] for x in f["qtypes"]}
    assert qt == {"scq": 3, "msq": 1, "int": 1, "num": 1, "mtx": 1}
    assert {x["value"]: x["count"] for x in f["difficulties"]} == {
        "Easy": 2, "Medium": 1, "Hard": 1}
    assert f["ungradedDifficulty"] == 3  # 7 done-paper questions, 4 graded
    groups = {tuple(i["raws"]): i for i in f["institutes"]}
    merged = groups[("BHASHYAM IIT-JEE ACADEMY", "Bhashyam IIT-JEE Academy")]
    assert merged["count"] == 4 and merged["name"] in merged["raws"]
    assert all("FIITJEE" not in i["raws"] for i in f["institutes"])
    assert f["years"] == [{"value": 2024, "count": 2},
                          {"value": 2025, "count": 3},
                          {"value": 2026, "count": 2}]
    # Fuzzy is suggestion-only: no auto-merge of distinct institutes.
    for s in f["instituteSuggestions"]:
        assert {s["a"], s["b"]} != {"FIITJEE", "Sri Chaitanya IIT Academy"}


def test_facets_invalidate_on_mutation(search_client):
    client, ids = search_client
    v0 = _get(client, "/api/search/facets")["version"]
    from backend.routers.search import bump_search_version
    bump_search_version()
    assert _get(client, "/api/search/facets")["version"] == v0 + 1


# ---------------------------------------------------------------- listing

def test_unfiltered_walk_covers_total_once(search_client):
    client, _ = search_client
    seen = []
    cur = None
    total = None
    while True:
        url = "/api/search?limit=3" + (f"&cursor={cur}" if cur else "")
        d = _get(client, url)
        total = total if total is not None else d["total"]
        assert d["total"] == total == 7
        seen += [(i["paperId"], i["number"]) for i in d["items"]]
        if not d["hasMore"]:
            assert d["nextCursor"] is None
            break
        cur = d["nextCursor"]
    assert len(seen) == 7 and len(set(seen)) == 7


def test_ids_ascending_stable_order(search_client):
    client, _ = search_client
    d1 = _get(client, "/api/search?limit=100")
    d2 = _get(client, "/api/search?limit=100")
    assert [(i["paperId"], i["number"]) for i in d1["items"]] == [
        (i["paperId"], i["number"]) for i in d2["items"]]


def test_intersection_across_filter_types(search_client):
    client, _ = search_client
    d = _get(client, "/api/search?qtype=scq&difficulty=Easy&limit=100")
    assert d["total"] == 2
    assert all(i["qtype"] == "scq" and i["difficulty"] == "Easy"
               for i in d["items"])


def test_union_within_filter_type(search_client):
    client, _ = search_client
    d = _get(client, "/api/search?qtype=scq&qtype=int&limit=100")
    assert d["total"] == 4  # 3 scq + 1 int


def test_cursor_bound_to_filters(search_client):
    client, _ = search_client
    d = _get(client, "/api/search?limit=2")
    r = client.get(f"/api/search?limit=2&cursor={d['nextCursor']}&qtype=scq")
    assert r.status_code == 400
    r = client.get("/api/search?limit=2&cursor=!!!not-base64!!!")
    assert r.status_code == 400


def test_bad_values_rejected(search_client):
    client, _ = search_client
    for path in ["/api/search?qtype=bogus",
                 "/api/search?difficulty=Extreme",
                 "/api/search?topic=NOPE",
                 "/api/search?main_topic=NOPE",
                 "/api/search?institute=Nowhere Academy"]:
        assert client.get(path).status_code == 400, path


def test_indexing_paper_excluded(search_client):
    client, _ = search_client
    d = _get(client, "/api/search?limit=100")
    assert all(i["paper"]["title"] != "Paper D" for i in d["items"])


# ---------------------------------------------------------------- topics

def _descendants(codes):
    conn = database.get_connection()
    try:
        tmap = {r["code"]: r["parent"] for r in conn.execute(
            "SELECT code, parent FROM topics").fetchall()}
        qrows = conn.execute(
            "SELECT question_id, topic_code FROM question_topics").fetchall()
    finally:
        conn.close()
    want = set()
    stack = list(codes)
    while stack:
        c = stack.pop()
        if c in want:
            continue
        want.add(c)
        stack += [k for k, p in tmap.items() if p == c]
    out = set()
    for r in qrows:
        if r["topic_code"] in want:
            out.add(r["question_id"])
    return out


def test_topic_expansion_matches_expected_set(search_client):
    client, ids = search_client
    for sel in [["M1"], ["PH01"], ["PH01-W1"], ["PH01.01"],
                ["M1", "PH01"], ["M2"], ["PH01.01", "PH13.14"]]:
        q = "&".join(f"topic={c}" for c in sel)
        d = _get(client, f"/api/search?{q}&limit=100")
        conn = database.get_connection()
        try:
            idrows = {(r["paper_id"], r["question_number"]): r["id"]
                      for r in conn.execute(
                          "SELECT id, paper_id, question_number FROM questions"
                          " WHERE paper_id != ?", (ids["p4"],)).fetchall()}
        finally:
            conn.close()
        expect = {k for k, v in idrows.items()
                  if v in _descendants(sel)}
        # Exclude indexing paper questions from expectation.
        got = {(i["paperId"], i["number"]) for i in d["items"]}
        assert got == expect, sel


def test_subtree_counts_are_distinct_questions(search_client):
    client, _ = search_client
    f = _get(client, "/api/search/facets")
    sub = f["topicSubtreeCounts"]
    # p1q1 carries two M1 tags: naive per-subtopic sums would give 4, but
    # only 3 distinct questions sit under M1.
    assert sub["M1"] == 3
    assert sub["PH01"] == 3
    assert sub["PH01-W1"] == 3
    assert sub["PH01.01"] == 2
    assert sub["PH01.02"] == 2
    assert sub["PH13.14"] == 1
    assert sub["M2"] == 1


def test_overlapping_selection_dedupes(search_client):
    client, _ = search_client
    m1 = _get(client, "/api/search?topic=M1&limit=100")
    both = _get(client, "/api/search?topic=M1&topic=PH01&limit=100")
    assert both["total"] == m1["total"] == 3


def test_main_topic_only_matches_rank_zero(search_client):
    client, ids = search_client
    # p1q1 tags PH01.02 at rank 1 only; p1q2 tags it at rank 0.
    any_tag = _get(client, "/api/search?topic=PH01.02&limit=100")
    main = _get(client, "/api/search?main_topic=PH01.02&limit=100")
    got_any = {(i["paperId"], i["number"]) for i in any_tag["items"]}
    got_main = {(i["paperId"], i["number"]) for i in main["items"]}
    assert got_any == {(ids["p1"], "1"), (ids["p1"], "2")}
    assert got_main == {(ids["p1"], "2")}
    # Parent expansion works the same way: M1-main matches all three
    # rank-0-M1 questions, and the rank-1-only tag never leaks in.
    m1_main = _get(client, "/api/search?main_topic=M1&limit=100")
    assert {(i["paperId"], i["number"]) for i in m1_main["items"]} == {
        (ids["p1"], "1"), (ids["p1"], "2"), (ids["p2"], "2")}
    # Both filters intersect.
    both = _get(client, "/api/search?topic=PH01.02&main_topic=PH13.14&limit=100")
    assert {(i["paperId"], i["number"]) for i in both["items"]} == {
        (ids["p1"], "2")}


def test_main_topic_facets_count_rank_zero_only(search_client):
    client, _ = search_client
    f = _get(client, "/api/search/facets")
    assert f["mainTopicCounts"]["PH01.02"] == 1  # rank-0 only, not 2
    assert f["mainTopicCounts"]["PH01.01"] == 2
    assert f["mainTopicSubtreeCounts"]["M1"] == 3
    assert f["mainTopicSubtreeCounts"]["PH01-W1"] == 3


def test_chapters_deterministic_first_plus_overflow(search_client):
    client, _ = search_client
    a = _get(client, "/api/search?topic=M1&limit=100")
    b = _get(client, "/api/search?topic=M1&limit=100")
    assert [(i["chapters"], i["chapterOverflow"]) for i in a["items"]] == [
        (i["chapters"], i["chapterOverflow"]) for i in b["items"]]
    multi = next(i for i in a["items"]
                 if {t["code"] for t in i["topics"]} == {"PH01.02", "PH13.14"})
    assert multi["chapters"] == ["Vectors", "Electrostatics"]
    assert multi["chapterOverflow"] == 0


# ---------------------------------------------------------------- cards

def test_card_preview_thumb_light(search_client):
    client, _ = search_client
    d = _get(client, "/api/search?limit=100")
    first = next(i for i in d["items"]
                 if i["paperId"] and i["number"] == "1")
    assert "x^2" in first["preview"] and "$" not in first["preview"]
    assert len(first["preview"]) <= 201
    assert first["thumb"].endswith("/figures/qfig1.png")
    nofig = next(i for i in d["items"] if i["thumb"] is None)
    assert nofig["preview"] != ""
    assert set(first) == {"paperId", "number", "qtype", "difficulty", "paper",
                          "chapters", "chapterOverflow", "topics", "preview",
                          "thumb"}


# ---------------------------------------------------------------- perf guard

def test_no_n_plus_one_db_queries(search_client, monkeypatch):
    client, _ = search_client
    calls = []
    real_connect = database.get_connection

    class Proxy:
        def __init__(self, conn):
            self._c = conn

        def execute(self, *a, **k):
            calls.append(1)
            return self._c.execute(*a, **k)

        def __getattr__(self, name):
            return getattr(self._c, name)

        def close(self):
            return self._c.close()

    monkeypatch.setattr(database, "get_connection",
                        lambda *a, **k: Proxy(real_connect(*a, **k)))
    d = _get(client, "/api/search?topic=M1&qtype=scq&limit=24")
    assert d["total"] >= 0
    # 1 page query + 1 count + 1 topics batch + 1 topics map + papers +
    # institutes + validation: must stay flat as questions grow.
    assert len(calls) <= 10, len(calls)


def test_search_indexes_exist(search_client):
    conn = database.get_connection()
    try:
        idx = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
    finally:
        conn.close()
    for name in ["idx_questions_paper", "idx_questions_qtype",
                 "idx_questions_difficulty", "idx_papers_exam",
                 "idx_papers_institute", "idx_papers_status",
                 "idx_qt_qid", "idx_qt_topic", "idx_topics_parent"]:
        assert name in idx, name
