"""Read-only previews of EJEE source images (body crop, downscaled, cached).

The original upload file is never modified; only the printed body box from
``print_meta`` is shown (the same region the importer extracts from).
"""
from __future__ import annotations

import io
import json
import sqlite3
import threading
from pathlib import Path

from store import data_dir

WIDTHS = (240, 480, 960, 1600)
_lock = threading.Lock()


def _row(ejee_db, rid):
    conn = sqlite3.connect(Path(ejee_db).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        return conn.execute("SELECT file_name, print_meta, mime FROM resources WHERE id=?", (rid,)).fetchone()
    finally:
        conn.close()


def preview(ejee_db: str, uploads: str, rid: int, width: int, full: bool = False) -> tuple[bytes, str] | None:
    width = min((w for w in WIDTHS if w >= width), default=WIDTHS[-1])
    cache = data_dir() / "thumbs" / f"{rid}_{width}{'_full' if full else ''}.png"
    if cache.is_file():
        return cache.read_bytes(), "image/png"
    row = _row(ejee_db, rid)
    if not row or not row[0]:
        return None
    base = Path(uploads).resolve()
    path = (base / row[0]).resolve()
    if base not in path.parents or not path.is_file() or not (row[2] or "image/").startswith("image/"):
        return None
    from PIL import Image
    with Image.open(path) as original:
        im = original.convert("RGB")
    if not full:
        try:
            box = (json.loads(row[1] or "{}") or {}).get("box") or (json.loads(row[1] or "{}") or {}).get("qbox")
        except ValueError:
            box = None
        if box and len(box) == 4 and 0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1:
            im = im.crop((int(box[0] * im.width), int(box[1] * im.height),
                          int(box[2] * im.width + 0.999), int(box[3] * im.height + 0.999)))
    if im.width > width:
        im = im.resize((width, max(1, round(im.height * width / im.width))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    data = buf.getvalue()
    with _lock:
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(cache)
    return data, "image/png"
