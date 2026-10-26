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

# Staging dir scanned by the Upload page. NOTE: bound at import for the
# long-lived UI process (env is fixed at startup there). Tests that need
# isolation must monkeypatch this name AND directory_manager.UPLOADS_DIR;
# patching directory_manager.DATA_ROOT alone does not rebind it.
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


_KEY_WORD_RE = re.compile(r"\b(answer\s?keys?|answerkey|keys?)\b")
_QM_WORD_RE = re.compile(r"\b(qp|questions?)\b")
# A separate key file ("Answer Key.pdf", "GTA Key & Sols") must stay a
# solution; only a key word PLUS an in-name question marker counts as a
# combined single file ("PTA-9 QP, Key & Solutions"). "Paper" alone is
# too generic (every "* Paper 1 Solutions.pdf" has it), so it only
# counts together with a solutions word.
_SOL_CONTENT_RE = re.compile(r"\b(solutions?|sols?|answers?)\b")


def is_combined_name(name: str) -> bool:
    """A single file holding Q + Key + Solutions (e.g. 'PTA-9 QP, Key & Solutions').

    Without this rule such files match ``is_solution_name`` and would
    leave the question list empty. Bare key files ("Answer Key.pdf",
    "Paper 1 Key.pdf", "GTA Key & Sols", "* Paper 1 Solutions.pdf")
    stay solutions; the UI's manual Same-file option covers filenames
    too ambiguous to call either way.
    """
    norm = _norm(name)
    if not _KEY_WORD_RE.search(norm):
        return False
    if _QM_WORD_RE.search(norm):
        return True
    residual = _KEY_WORD_RE.sub(" ", norm)
    return bool(
        re.search(r"\bpaper\b", residual) and _SOL_CONTENT_RE.search(residual)
    )


def split_candidates(names: list[str]) -> tuple[list[str], list[str]]:
    """Partition staged files into (questions, solutions). Exhaustive.

    Combined single files (Q + Key + Sol in one PDF) count as questions;
    the UI offers 'same file' as their solution pairing.
    """
    questions = [n for n in names if is_combined_name(n) or not is_solution_name(n)]
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


def save_uploads(files, dest: Path | None = None) -> list[str]:
    """Persist uploaded files (objects with .name/.getbuffer or paths)."""
    dest = Path(dest) if dest is not None else directory_manager.UPLOADS_DIR
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
    try:
        cleaned_root = directory_manager.CLEANED_DIR.resolve()
    except OSError:
        cleaned_root = None
    # Combined flow: both columns point at the same file -- move once,
    # point both at the destination (deleting the source once).
    import os as _os

    q_str = row["question_pdf_path"]
    if cleaned_root is not None and q_str:
        try:
            if Path(q_str).resolve().is_relative_to(cleaned_root):
                return False  # derived copy already pinned; nothing to move
        except OSError:
            pass
    if (row["solution_pdf_path"] and q_str and _os.path.realpath(
            row["solution_pdf_path"]) == _os.path.realpath(q_str)):
        src = Path(q_str)
        if src.is_file() and _is_within(src, root):
            dest = _dest_for(dest_dir, src, paper_id)
            if dest.resolve() != src.resolve():
                if not dest.exists() or dest.read_bytes() != src.read_bytes():
                    tmp = dest.with_name(dest.name + ".part")
                    shutil.copy2(str(src), str(tmp))
                    tmp.rename(dest)
                database.update_paper_paths(paper_id, str(dest), str(dest))
                try:
                    if src.is_file():
                        src.unlink()
                except OSError:
                    pass
                return True
            return False
    for col in ("question_pdf_path", "solution_pdf_path"):
        src_str = row[col]
        if not src_str:
            new_paths[col] = None
            continue
        src = Path(src_str)
        if not src.is_file() or not _is_within(src, root):
            new_paths[col] = src_str
            continue
        if cleaned_root is not None:
            try:
                if src.resolve().is_relative_to(cleaned_root):
                    # Derived cache (split/cleaned/crop copies): pinned where
                    # the pipeline wrote them, never swept into archive/.
                    new_paths[col] = src_str
                    continue
            except OSError:
                pass
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
    # Derived per-paper files (split + cleaned/crop copies) live in
    # CLEANED_DIR and are otherwise orphaned forever.
    try:
        cdir = directory_manager.CLEANED_DIR
        if cdir.is_dir():
            for p in cdir.glob(f"{int(paper_id):02d}_*"):
                try:
                    if p.is_file():
                        p.unlink()
                except OSError:
                    pass
    except OSError:
        pass
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
    try:
        cleaned_root = directory_manager.CLEANED_DIR.resolve()
    except OSError:
        cleaned_root = None
    removed = []
    for r in rows:
        paths = [r["question_pdf_path"]]
        if r["solution_pdf_path"]:
            paths.append(r["solution_pdf_path"])
        doomed = False
        for p in paths:
            if Path(p).is_file():
                continue
            if cleaned_root is not None:
                try:
                    if Path(p).resolve().is_relative_to(cleaned_root):
                        # Derived split/cleaned copy: the split node
                        # rebuilds it from the question file on next run.
                        continue
                except OSError:
                    pass
            doomed = True
        if doomed:
            if delete_paper_everywhere(int(r["id"])):
                removed.append(int(r["id"]))
    return removed
