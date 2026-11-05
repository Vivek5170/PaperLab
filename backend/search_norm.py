"""Canonical institute names for /api/search.

Safeguards (per approved plan):
- Exact normalized matches merge automatically (case/whitespace/punctuation
  differences only, e.g. "Bhashyam ..." vs "BHASHYAM ...").
- KNOWN_ALIASES maps normalized keys that differ textually but are known to
  be the same institute. Curated by hand; never guessed.
- Fuzzy matching is suggestion-only (suggest_merges): pairs above threshold
  are reported in the facets payload for a human to review, never merged.
- Original database values are never modified; facets expose the raw
  variants behind each canonical name, and search expands a canonical
  filter to its raw variants in SQL.
"""
from __future__ import annotations

import difflib
import re
import unicodedata

# normalized-key -> normalized-key it is known to alias. Both sides are
# canon_key() outputs, not raw names. Empty until a human confirms a pair
# (candidates come from suggest_merges).
KNOWN_ALIASES: dict[str, str] = {}


def canon_key(raw: str | None) -> str:
    """Normalize for equality: strip, collapse spaces, drop punctuation, fold case."""
    s = unicodedata.normalize("NFKC", str(raw or "")).strip()
    s = re.sub(r"\s+", " ", s).casefold()
    return re.sub(r"[^0-9a-z]+", "", s)


def _display_name(raws: list[str], counts: dict[str, int]) -> str:
    """Deterministic display: most frequent raw, ties -> smallest raw."""
    return sorted(raws, key=lambda r: (-counts.get(r, 0), r))[0]


def group_institutes(rows: list[tuple[str | None, int]]) -> list[dict]:
    """Merge [(raw_name, question_count)] into canonical groups.

    Returns [{name, key, raws, count}] sorted by name. Rows with a blank
    name are folded into a single "Unknown" group.
    """
    by_key: dict[str, dict[str, int]] = {}
    for raw, n in rows:
        key = canon_key(raw) if (raw or "").strip() else "unknown"
        label = raw or "Unknown"
        by_key.setdefault(key, {})
        by_key[key][label] = by_key[key].get(label, 0) + (n or 0)
    # Apply curated aliases: fold alias key into its target key.
    for alias, target in KNOWN_ALIASES.items():
        if alias in by_key and target in by_key and alias != target:
            for raw, n in by_key.pop(alias).items():
                by_key[target][raw] = by_key[target].get(raw, 0) + n
    groups = []
    for key, variants in by_key.items():
        raws = sorted(variants)
        total = sum(variants.values())
        name = "Unknown" if key in ("unknown", "") else _display_name(raws, variants)
        groups.append({"name": name, "key": key, "raws": raws, "count": total})
    groups.sort(key=lambda g: g["name"].casefold())
    return groups


def expand_canonical(names: list[str], groups: list[dict]) -> list[str]:
    """Canonical display names -> underlying raw DB values for SQL IN."""
    by_name = {g["name"]: g["raws"] for g in groups}
    out: list[str] = []
    for n in names:
        if n not in by_name:
            raise ValueError(f"unknown institute filter {n!r}")
        out.extend(by_name[n])
    return sorted(set(out))


def suggest_merges(groups: list[dict], threshold: float = 0.82) -> list[dict]:
    """Fuzzy candidate pairs across canonical keys. Suggestion-only: the
    caller must never auto-merge these; a human curates KNOWN_ALIASES."""
    keys = [g for g in groups if g["key"] not in ("unknown", "")]
    out = []
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = keys[i]["key"], keys[j]["key"]
            score = difflib.SequenceMatcher(None, a, b).ratio()
            if score >= threshold:
                out.append({"a": keys[i]["name"], "b": keys[j]["name"],
                            "score": round(score, 3)})
    out.sort(key=lambda d: -d["score"])
    return out
