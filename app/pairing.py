"""Upload staging, fuzzy question/solution pairing, registration."""
from __future__ import annotations

import difflib
import re
from pathlib import Path

import database
from preflight import preflight_register

UPLOAD_DIR = Path(__file__).parent.parent / "uploads"
PAIR_THRESHOLD = 0.35


def stem(name: str) -> str:
    """Normalize a filename for fuzzy matching: lower, no ext, uniform seps."""
    s = Path(name).stem.lower()
    s = re.sub(r"[\s_\-]+", " ", s)
    s = re.sub(r"\b(solutions?|sols?|key|answers?)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def auto_pair(q_names: list[str], s_names: list[str]) -> list[tuple[str, str | None]]:
    """Greedy best-match pairing of question PDFs to solution PDFs.

    Returns [(question, solution|None)]. Unmatched questions get None.
    """
    remaining = list(s_names)
    pairs: list[tuple[str, str | None]] = []
    for q in q_names:
        best, best_score = None, 0.0
        for s in remaining:
            score = difflib.SequenceMatcher(None, stem(q), stem(s)).ratio()
            if score > best_score:
                best, best_score = s, score
        if best is not None and best_score >= PAIR_THRESHOLD:
            remaining.remove(best)
            pairs.append((q, best))
        else:
            pairs.append((q, None))
    return pairs


def save_uploads(files, dest: Path = UPLOAD_DIR) -> list[str]:
    """Persist uploaded files (objects with .name/.getbuffer or paths)."""
    dest.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        name = Path(getattr(f, "name", str(f))).name
        target = dest / name
        if hasattr(f, "getbuffer"):
            target.write_bytes(bytes(f.getbuffer()))
        elif str(f) != str(target):
            import shutil

            shutil.copy(str(f), target)
        saved.append(str(target))
    return saved


def register_pair(question_path: str, solution_path: str | None) -> tuple[int, bool]:
    """Register a pair; returns (paper_id, reused_existing).

    Duplicate pairs reuse the existing paper instead of erroring.
    """
    try:
        return preflight_register(question_path, solution_path), False
    except database.DuplicatePaperError:
        row = database.find_paper_by_hash(
            database.compute_paper_hash(question_path, solution_path)
        )
        return int(row["id"]), True
