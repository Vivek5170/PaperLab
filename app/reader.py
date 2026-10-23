"""Reader helpers: pure logic for the paper library (no Streamlit calls)."""
from __future__ import annotations


def question_ids(rows: list) -> list[str]:
    """Ordered question numbers from DB rows."""
    return [r["question_number"] for r in rows]


def neighbor_ids(ids: list[str], current: str) -> tuple[str | None, str | None]:
    """(prev, next) around current; None at the ends."""
    try:
        i = ids.index(current)
    except ValueError:
        return None, ids[0] if ids else None
    prev_id = ids[i - 1] if i > 0 else None
    next_id = ids[i + 1] if i + 1 < len(ids) else None
    return prev_id, next_id


def paper_title(row) -> str:
    name = row["paper_name"] or f"Paper {row['id']}"
    exam = row["exam_type"] or "Unknown exam"
    date = row["paper_date"] or "undated"
    return f"{name} · {exam} · {date}"
