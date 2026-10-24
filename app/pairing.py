"""Upload staging, fuzzy question/solution pairing, registration, lifecycle.

Source-PDF lifecycle: ``data/uploads/`` (staged) -> ``data/processing/``
(confirmed) -> ``data/archive/`` (done). Only files under the managed
``data/`` tree are ever moved or swept; outside paths (``example_data/``,
``/tmp``, CLI one-offs) are left alone.
"""
from __future__ import annotations

import difflib
import re
import shutil
from pathlib import Path

import database
import directory_manager
from preflight import preflight_register

# Staging dir scanned by the Upload page; an alias of the managed layout.
UPLOAD_DIR = directory_manager.UPLOADS_DIR
PAIR_THRESHOLD = 0.35


def _norm(name: str) -> str:
    """Lowercased stem with uniform separators (underscores kill \b)."""
    return re.sub(r"[\s_\-]+", " ", Path(name).stem.lower())


_SOL_WORD_RE = re.compile(
    r"\b(solutions?|sols?|answer\s?keys?|answerkey|keys?|answers?)\b")


def stem(name: str) -> str:
    """Normalize a filename for fuzzy matching: lower, no ext, uniform seps."""
    s = _SOL_WORD_RE.sub(" ", _norm(name))
    return re.sub(r"\s+", " ", s).strip()


def is_solution_name(name: str) -> bool:
    """Same keyword rule as stem(): word-boundary match on normalized stem."""
    return bool(_SOL_WORD_RE.search(_norm(name)))


def split_candidates(names: list[str]) -> tuple[list[str], list[str]]:
    """Partition staged files into (questions, solutions). Exhaustive."""
    questions = [n for n in names if not is_solution_name(n)]
    solutions = [n for n in names if n not in questions]
    return questions, solutions


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
    Fresh registrations inside the managed tree advance to processing/.
    """
    try:
        pid = preflight_register(question_path, solution_path)
        relocate_managed_files(pid, directory_manager.PROCESSING_DIR)
        return pid, False
    except database.DuplicatePaperError:
        row = database.find_paper_by_hash(
            database.compute_paper_hash(question_path, solution_path)
        )
        return int(row["id"]), True


def _is_within(path: Path, root: Path) -> bool:
    """True if path resolves inside root (symlink-safe containment)."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _dest_for(dest_dir: Path, src: Path, paper_id: int) -> Path:
    """Destination path; prefix paper_id on name clash with different bytes."""
    dest = dest_dir / src.name
    if dest.exists() and dest.read_bytes() != src.read_bytes():
        dest = dest_dir / f"{paper_id}_{src.name}"
    return dest


def relocate_managed_files(paper_id: int, dest_dir: str | Path) -> bool:
    """Move a paper's source PDFs into dest_dir if managed; update DB paths.

    Only files under the managed ``data/`` tree are moved; outside paths
    are left untouched. Missing files are skipped. Returns True if anything
    changed. Raises ValueError for an unknown paper_id.

    Crash ordering is copy -> commit -> unlink-originals: at every instant
    the DB points at existing files, so the startup sweep can never mistake
    a half-moved paper for a deleted one. A crash may leave a duplicate
    copy behind, never a dangling pointer.
    """
    row = database.get_paper(paper_id)
    if row is None:
        raise ValueError(f"paper_id {paper_id} does not exist")
    root = directory_manager.DATA_ROOT
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    new_paths: dict[str, str | None] = {}
    originals: list[Path] = []
    changed = False
    for col in ("question_pdf_path", "solution_pdf_path"):
        src_str = row[col]
        if not src_str:
            new_paths[col] = None
            continue
        src = Path(src_str)
        if not src.is_file() or not _is_within(src, root):
            new_paths[col] = src_str
            continue
        dest = _dest_for(dest_dir, src, paper_id)
        if dest.resolve() == src.resolve():
            new_paths[col] = str(src)
            continue
        if not dest.exists() or dest.read_bytes() != src.read_bytes():
            tmp = dest.with_name(dest.name + ".part")
            shutil.copy2(str(src), str(tmp))
            tmp.rename(dest)
        new_paths[col] = str(dest)
        originals.append(src)
        changed = True
    if changed:
        database.update_paper_paths(
            paper_id, new_paths["question_pdf_path"], new_paths["solution_pdf_path"]
        )
        for src in originals:
            try:
                if src.is_file():
                    src.unlink()
            except OSError:
                pass
    return changed


def delete_paper_everywhere(paper_id: int) -> bool:
    """Hard-delete a paper: DB row (cascades), managed source PDFs, Outputs/.

    Files outside the managed ``data/`` tree are never touched. The DB row
    goes first so a live row never points at deleted files; returns True if
    the paper existed.
    """
    row = database.get_paper(paper_id)
    if row is None:
        return False
    root = directory_manager.DATA_ROOT
    doomed = []
    for col in ("question_pdf_path", "solution_pdf_path"):
        src_str = row[col]
        if not src_str:
            continue
        p = Path(src_str)
        try:
            if p.is_file() and _is_within(p, root):
                doomed.append(p)
        except OSError:
            pass
    database.delete_paper(paper_id)
    for p in doomed:
        try:
            if p.is_file():
                p.unlink()
        except OSError:
            pass
    out = directory_manager.paper_dir(paper_id)
    if out.is_dir():
        shutil.rmtree(out, ignore_errors=True)
    return True


def reconcile_missing_sources() -> list[int]:
    """Hard-delete every non-done paper whose source PDFs are gone.

    Done (archived) papers are exempt: their files may be deleted offline
    with no effect. Returns the removed paper ids.
    """
    conn = database.get_connection()
    try:
        rows = conn.execute(
            "SELECT id, question_pdf_path, solution_pdf_path FROM papers "
            "WHERE COALESCE(status, 'uploaded') != 'done'"
        ).fetchall()
    finally:
        conn.close()
    removed = []
    for r in rows:
        paths = [r["question_pdf_path"]]
        if r["solution_pdf_path"]:
            paths.append(r["solution_pdf_path"])
        if any(not Path(p).is_file() for p in paths):
            if delete_paper_everywhere(int(r["id"])):
                removed.append(int(r["id"]))
    return removed
