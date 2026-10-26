"""Strict output directory manager.

Output base resolved by ``config.py`` (``config.yaml`` > ``PHYSICS_OUTPUT_BASE``
env > default ``Outputs/`` next to the source). Every entry point must
``import config`` before this module so all stages share one Outputs tree.

Enforces the exact hierarchy::

    Outputs/{paper_id}/{question_number}/
        question.tex
        solution.tex
        figures/

``question_number`` is treated as an opaque string so grouped comprehensions
like ``"15-17_paragraph"`` or sub-parts like ``"15a"`` are preserved verbatim.
"""

from __future__ import annotations

import os
from pathlib import Path

import config  # noqa: F401 -- must precede OUTPUT_BASE: pins env from config.yaml

OUTPUT_BASE = Path(os.environ.get("PHYSICS_OUTPUT_BASE", Path(__file__).parent / "Outputs"))

# Managed source-PDF lifecycle root: uploads/ (staged) -> processing/
# (confirmed) -> archive/ (done). Only files under DATA_ROOT are ever
# moved or swept; outside paths (example_data/, /tmp, CLI one-offs) are
# left alone. The *_DIR constants below bind at import: tests must patch
# each DIR they touch (patching DATA_ROOT alone does not rebind them).
DATA_ROOT = Path(os.environ.get("DATA_ROOT", Path(__file__).parent / "data"))
UPLOADS_DIR = DATA_ROOT / "uploads"
PROCESSING_DIR = DATA_ROOT / "processing"
ARCHIVE_DIR = DATA_ROOT / "archive"
# Extractor-vision copies: hash-named cleaned PDFs (originals stay in DB).
CLEANED_DIR = DATA_ROOT / "cleaned"

QUESTION_TEX = "question.tex"
SOLUTION_TEX = "solution.tex"
FIGURES_DIR = "figures"
SOLUTION_PLACEHOLDER = "\\textit{No solution provided.}"


def _base(output_base: str | Path | None = None) -> Path:
    if output_base is not None:
        return Path(output_base)
    # Re-read env at call time so tests can monkeypatch env vars.
    return Path(os.environ.get("PHYSICS_OUTPUT_BASE", OUTPUT_BASE))


def safe_component(value: str | int, name: str) -> str:
    """Validate a single path component (paper_id / question_number / filename).

    Rejects absolute paths, parent-directory escapes (".."), path separators
    and empty values so LLM-supplied identifiers cannot escape the Outputs
    tree. Raises ValueError on violation.
    """
    text = str(value)
    if not text or text in (".", ".."):
        raise ValueError(f"Invalid {name}: {text!r}")
    if os.path.isabs(text):
        raise ValueError(f"Invalid {name}: absolute paths are not allowed: {text!r}")
    if "/" in text or "\\" in text or os.sep in text:
        raise ValueError(
            f"Invalid {name}: path separators are not allowed: {text!r}"
        )
    if ".." in text.split("/"):
        raise ValueError(f"Invalid {name}: parent escape is not allowed: {text!r}")
    return text


def get_question_dir(
    paper_id: int, question_number: str, output_base: str | Path | None = None
) -> Path:
    """Return the path ``Outputs/{paper_id}/{question_number}`` (no creation)."""
    base = _base(output_base)
    return (
        base
        / safe_component(paper_id, "paper_id")
        / safe_component(question_number, "question_number")
    )


def ensure_question_dir(
    paper_id: int, question_number: str, output_base: str | Path | None = None
) -> Path:
    """Create (if needed) the question folder and its ``figures/`` subfolder.

    Returns the question directory path.
    """
    qdir = get_question_dir(paper_id, question_number, output_base)
    (qdir / FIGURES_DIR).mkdir(parents=True, exist_ok=True)
    return qdir


def paper_dir(paper_id: int, output_base: str | Path | None = None) -> Path:
    """Return the path ``Outputs/{paper_id}`` (no creation)."""
    return _base(output_base) / str(paper_id)
