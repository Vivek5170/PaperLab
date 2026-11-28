"""EJEE chapter import: read-only source -> mapped image PDFs -> Node 2 -> Node 3.

Usage: python importer.py <phase> --config runs/books/<book>/part-NNN.json   (see README.md)
   Step 1 (staging): prepare..verify write only the run's temp DB.
   Step 2 (merge):  python importer.py merge --config run.json --target-db /path/to/physics_archive.db
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import io
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import time

from bootstrap import ROOT, REPO, activate


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def source_connect(path):
    conn = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA query_only=ON')
    conn.execute('BEGIN')  # consistent snapshot including the live WAL
    return conn


def load_config(path):
    path = Path(path).resolve()
    cfg = json.loads(path.read_text(encoding='utf-8-sig'))  # tolerate BOM (Notepad/PowerShell)
    # EJEE prepare() always creates raster body canvases. Native PDF cropping
    # remains an explicit compatibility option, not the raster default.
    cfg.setdefault('raster_exact_crop', True)
    for key in ('source_db', 'asset_root', 'original_pdf', 'book_plan'):
        if cfg.get(key) and not Path(cfg[key]).is_absolute():
            cfg[key] = str((path.parent / cfg[key]).resolve())
    run = (ROOT / cfg['run_dir'])
    from pathlib import PurePosixPath, PureWindowsPath
    if PurePosixPath(cfg['run_dir']).is_absolute() or PureWindowsPath(cfg['run_dir']).is_absolute():
        raise ValueError('run_dir must be a relative path inside importer_EJEE')
    run = run.resolve()
    if ROOT not in run.parents or REPO == run or ROOT / 'reference' in run.parents or (REPO != ROOT.parent and REPO in run.parents):
        raise ValueError('Invalid run directory')
    return cfg, run


def ident(name):
    return '"' + name.replace('"', '""') + '"'


def inspect_source(cfg, run):
    with source_connect(cfg['source_db']) as c:
        tables = []
        for row in c.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name"):
            tables.append({'name': row['name'], 'sql': row['sql'],
                           'count': c.execute('SELECT count(*) FROM ' + ident(row['name'])).fetchone()[0],
                           'columns': [dict(v) for v in c.execute('PRAGMA table_info(' + ident(row['name']) + ')')]})
        dump(run / 'source_schema.json', tables)
        books = [dict(r) for r in c.execute('SELECT source,part,count(*) count FROM resources GROUP BY source,part ORDER BY source,part')]
        dump(run / 'source_inventory.json', books)
    write_mapping(tables, run)
    print(f'Inspected {len(tables)} tables; wrote schema, inventory and column mapping.', flush=True)


RESOURCE_MAP = {
    'id': 'Stable resource provenance; group membership and resume identity.',
    'uid': 'Preserved provenance; not a PaperLab question ID.',
    'grp': 'Exact question–answer join WITH source. Never match by similar titles.',
    'part': 'q -> question pages; sol -> ordered solution pages. Other roles require explicit handling.',
    'source': 'Exact textbook name -> papers.source_institute.',
    'title': 'Source label, original numbering and continuation-order evidence; preserved in manifest.',
    'position': 'Order evidence within a group; numeric continuation titles take precedence.',
    'file_name': 'Primary source asset under uploads; hash and crop losslessly.',
    'file_alt': 'Preserve provenance only; do not silently substitute an altered image.',
    'file_orig': 'Preserved original filename for traceability.',
    'mime': 'Asset validation/provenance; image decoded by Pillow.',
    'print_meta': 'Use box as normalized BODY bounds only; qbox is a fallback. keys/mask/qn are not diagram boxes. Preserve entire JSON.',
    'question': 'Existing transcription as auxiliary evidence only; image remains authoritative.',
    'answer': 'Existing answer evidence, checked against source; never synthesize a new answer.',
    'solution': 'Existing solution evidence; map with group images, never generate a worked solution.',
    'topic_id': 'Retain original node ancestry in provenance ONLY. Never seed PaperLab topics.',
    'difficulty': 'Provenance ONLY; PaperLab Node 3 reclassifies from imported TeX.',
    'tags': 'Provenance ONLY; no automatic topic assignment from EJEE.',
    'qtype': 'Source format evidence for Node 2; never map subjective to numeric automatically.',
    'type': 'Provenance and source format evidence; target schema has no subjective code, use unknown if needed.',
    'src_doc': 'Preserve locator; not a PDF path unless independently resolved.',
    'exam': 'Preserve only: textbooks use exam_type=Textbook, not historical exam labels.',
    'year': 'Preserve only: do not invent paper_date from textbook publication or import year.',
    'shift': 'Preserve only: no shift for chapter papers.',
}


def write_mapping(tables, run):
    used = {'resources', 'nodes', 'resource_crops', 'source_documents', 'resource_transcripts'}
    out = ['# EJEE column disposition', '',
           'Generated from the actual source schema. No source table or row is deleted. “Omitted” means excluded from the target PaperLab database; selected resource rows retain every original column in manifest.json. Student data is not exported.', '',
           'The current database has no tb_chapter table. Textbook chapter numbers are decoded from an explicit configured grp pattern; nodes is the teaching taxonomy and must not be substituted for book chapter order.', '']
    for table in tables:
        name = table['name']
        out += [f'## `{name}` ({table["count"]:,} rows)', '', '| Column | Disposition and reason |', '|---|---|']
        for col in table['columns']:
            field = col['name']
            if name == 'resources':
                desc = RESOURCE_MAP.get(field, 'Preserved in selected resource provenance; omitted from PaperLab because it is EJEE UI/editor state, not archival question content or fresh extraction statistics.')
            elif name == 'nodes':
                desc = 'Preserved in selected resource ancestry. Original teaching classification is provenance only; Node 3 supplies all target classification.'
            elif name == 'resource_crops':
                desc = 'Inspect for selected resources. Only explicit diagram/solution_diagram roles with validated image/coordinate frames qualify for reuse; question/solution boxes are not isolated diagrams. Preserve linked records.'
            elif name == 'source_documents':
                desc = 'Preserve selected crop-source linkage and locator/hash. Resolve and validate asset before coordinate reuse.'
            elif name == 'resource_transcripts':
                desc = 'Preserve selected versions and review/hold metadata as evidence; no unreviewed text replaces source pixels.'
            else:
                desc = 'Omitted from target: ' + (
                    'SQLite internal sequence; target generates its own IDs.' if name == 'sqlite_sequence' else
                    'EJEE worksheet composition, not textbook question ownership.' if name in {'papers', 'paper_items'} else
                    'Handwritten annotation state; not printed source content.' if name == 'strokes' else
                    'Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope.')
            out.append(f'| `{field}` | {desc} |')
        out.append('')
    (run / 'EJEE_COLUMN_MAPPING.md').write_text('\n'.join(out), encoding='utf-8')


def part_order(row):
    m = re.search(r'\((\d+)\s*/\s*\d+\)', row['title'] or '')
    return (int(m.group(1)) if m else 1, row['position'], row['id'])


def body_image(row, asset_root):
    from PIL import Image
    path = (Path(asset_root) / row['file_name']).resolve()
    base = Path(asset_root).resolve()
    if base not in path.parents or not path.is_file():
        raise ValueError(f'Missing/unsafe source image for resource {row["id"]}')
    with Image.open(path) as original:
        im = original.convert('RGB')
    meta = json.loads(row.get('print_meta') or '{}')
    box = meta.get('box') or meta.get('qbox')
    if not box or len(box) != 4 or not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1):
        raise ValueError(f'No valid body box for resource {row["id"]}; explicit adapter required')
    import math
    px = [math.floor(box[0]*im.width), math.floor(box[1]*im.height),
          math.ceil(box[2]*im.width), math.ceil(box[3]*im.height)]
    return im.crop(px), {'path': str(path), 'sha256': sha(path), 'body_box': box, 'body_box_px': px, 'original_size': list(im.size)}


def resolve_merges(cfg, selected):
    """Validate the explicit passage-merge map; no guessing involved.

    Config form: ``merge_groups: {"3-5_paragraph": ["morin-1.3", ...]}`` --
    local question number -> ordered source groups. Every listed group must
    already be selected (pattern + chapter + allowlist); no group may appear
    in two merges; local numbers must be unique and filesystem-safe (checked
    again against unmerged numbers by the caller). A shared passage split
    across EJEE groups is a cataloguing fact, not something to infer from
    pixels -- unlisted splits stay separate questions (fail-open, never
    silently merged).
    """
    merges = cfg.get('merge_groups') or {}
    if not isinstance(merges, dict):
        raise ValueError('merge_groups must be {local_number: [groups...]}')
    seen: set[str] = set()
    for number, grps in merges.items():
        number = str(number)
        if not number or '/' in number or '\\' in number or number in ('.', '..'):
            raise ValueError(f'Bad merge question number {number!r}')
        if not isinstance(grps, list) or len(grps) < 2 or any(not isinstance(g, str) for g in grps):
            raise ValueError(f'Merge {number!r} needs a list of 2+ group names')
        for g in grps:
            if g not in selected:
                raise ValueError(f'Merge {number!r} lists {g!r}, which is not a selected group '
                                 f'(pattern/chapter/allowlist mismatch?)')
            if g in seen:
                raise ValueError(f'Group {g!r} is listed in two merges')
            seen.add(g)
    return {str(k): list(v) for k, v in merges.items()}


def enrich_items(c, items):
    """Attach crops, transcripts and node ancestry (provenance only)."""
    nodes = {r['id']: dict(r) for r in c.execute('SELECT * FROM nodes')}
    for item in items:
        rid = [r['id'] for r in item['question_rows'] + item['solution_rows']]
        placeholders = ','.join('?' for _ in rid)
        item['resource_crops'] = [dict(r) for r in c.execute(f'SELECT * FROM resource_crops WHERE resource_id IN ({placeholders})', rid)]
        item['resource_transcripts'] = [dict(r) for r in c.execute(f'SELECT * FROM resource_transcripts WHERE resource_id IN ({placeholders})', rid)]
        ancestry = {}
        for r in item['question_rows'] + item['solution_rows']:
            lineage, n, seen = [], r['topic_id'], set()
            while n in nodes and n not in seen:
                seen.add(n); lineage.append(nodes[n]); n = nodes[n]['parent_id']
            ancestry[str(r['id'])] = lineage
        item['original_ancestry'] = ancestry
    return items


def book_plan_path(cfg):
    import book_plan
    return Path(cfg.get('book_plan') or ROOT / 'runs' / 'books' / book_plan.slug(cfg['book_source']) / 'plan.json')


def book_part_items(cfg):
    """Book mode: one frozen plan per source, ~part_size questions per paper."""
    import book_plan
    plan_path = book_plan_path(cfg)
    if not plan_path.is_file():
        raise ValueError(f'No frozen plan at {plan_path}; run: importer.py plan --config <cfg>')
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    if plan.get('schema') != book_plan.PLAN_SCHEMA or plan['source'] != cfg['book_source']:
        raise ValueError('Plan schema/source mismatch')
    part = int(cfg['part'])
    with source_connect(cfg['source_db']) as c:
        items = enrich_items(c, book_plan.part_items(c, plan, part))
    return items, f'{cfg["book_source"]} — Part {part}', plan_path


def prepare(cfg, run):
    if (run / 'manifest.json').exists():
        raise ValueError('Run already prepared; use extract/classify to resume, or choose a new run_dir')
    if cfg.get('part') is not None:
        items, paper_name, plan_path = book_part_items(cfg)
        return materialize(cfg, run, items, paper_name, {'book_plan': str(plan_path), 'part': int(cfg['part'])})
    try:
        pattern = re.compile(cfg['group_pattern'])
    except re.error as exc:
        raise ValueError(f'Invalid group_pattern: {exc}')
    if set(pattern.groupindex) < {'chapter', 'number'}:
        raise ValueError('group_pattern must define (?P<chapter>...) and (?P<number>...) groups')
    with source_connect(cfg['source_db']) as c:
        groups = defaultdict(list)
        for row in c.execute('SELECT * FROM resources WHERE source=? ORDER BY position,id', (cfg['book_source'],)):
            row = dict(row)
            m = pattern.fullmatch(row['grp'] or '')
            if m and m['chapter'] == str(cfg['chapter']) and (not cfg.get('groups') or row['grp'] in cfg['groups']):
                groups[row['grp']].append(row)
        if not groups:
            raise ValueError('No resources match the configured source and chapter')
        nodes = {r['id']: dict(r) for r in c.execute('SELECT * FROM nodes')}
        merges = resolve_merges(cfg, set(groups))
        merged_grps = {g for gs in merges.values() for g in gs}
        allow = cfg.get('groups')
        if allow and any(g not in allow for g in merged_grps):
            missing = sorted(g for g in merged_grps if g not in allow)
            raise ValueError(f'Merged groups {missing} are outside the allowlist; list them explicitly')

        def constituent(grps):
            qrows, srows = [], []
            for grp in grps:
                rows = groups[grp]
                if any(r['part'] not in ('q', 'sol') for r in rows):
                    raise ValueError(f'Unsupported part in {grp}; explicit adapter required')
                qq = sorted([r for r in rows if r['part'] == 'q'], key=part_order)
                if len(qq) > 1 and not all(re.search(r'\(\d+/\d+\)', r['title']) for r in qq):
                    raise ValueError(f'Ambiguous multiple question rows in {grp}')
                qrows.extend(qq)
                srows.extend(sorted([r for r in rows if r['part'] == 'sol'], key=part_order))
            if not qrows:
                raise ValueError(f'Orphan solution group {"+".join(grps)}')
            return qrows, srows

        items = []
        plans = []  # (sort_key, number, grps, merged?)
        for grp in sorted(groups, key=lambda g: int(pattern.fullmatch(g)['number'])):
            if grp in merged_grps:
                continue
            plans.append((int(pattern.fullmatch(grp)['number']), str(int(pattern.fullmatch(grp)['number'])), [grp], False))
        for number, grps in merges.items():
            plans.append((min(int(pattern.fullmatch(g)['number']) for g in grps), number, list(grps), True))
        numbers = [n for _, n, _, _ in plans]
        if len(set(numbers)) != len(numbers):
            raise ValueError(f'Merge numbers collide with chapter numbers: {numbers}')
        for _, number, grps, merged in sorted(plans):
            qrows, srows = constituent(grps)
            rid = [r['id'] for r in qrows + srows]
            placeholders = ','.join('?' for _ in rid)
            crops = [dict(r) for r in c.execute(f'SELECT * FROM resource_crops WHERE resource_id IN ({placeholders})', rid)]
            transcripts = [dict(r) for r in c.execute(f'SELECT * FROM resource_transcripts WHERE resource_id IN ({placeholders})', rid)]
            ancestry = {}
            for r in qrows + srows:
                lineage, n, seen = [], r['topic_id'], set()
                while n in nodes and n not in seen:
                    seen.add(n); lineage.append(nodes[n]); n = nodes[n]['parent_id']
                ancestry[str(r['id'])] = lineage
            nums = [pattern.fullmatch(g)['number'] for g in grps]
            items.append({'group': grps[0], 'groups': list(grps), 'merged': merged,
                          'number': number,
                          'source_number': '+'.join(f'{cfg["chapter"]}.{n}' for n in nums),
                          'question_rows': qrows, 'solution_rows': srows, 'original_ancestry': ancestry,
                          'resource_crops': crops, 'resource_transcripts': transcripts,
                          'question_pages': [], 'solution_pages': []})
    return materialize(cfg, run, items,
                       f'{cfg["book_source"]} — Chapter {cfg["chapter"]}: {cfg["chapter_title"]}', {})


def materialize(cfg, run, items, paper_name, extra):
    import fitz
    import database
    run.mkdir(parents=True, exist_ok=True)
    assets = run / 'sources'; assets.mkdir(exist_ok=True)
    qpdf, spdf = fitz.open(), fitz.open()
    for item in items:
        for side, doc in [('question', qpdf), ('solution', spdf)]:
            for row in item[f'{side}_rows']:
                im, evidence = body_image(row, cfg['asset_root'])
                buffer = io.BytesIO(); im.save(buffer, format='PNG')
                png = assets / f'{row["id"]}-body.png'; png.write_bytes(buffer.getvalue())
                page = doc.new_page(width=im.width * 72 / 200, height=im.height * 72 / 200)
                page.insert_image(page.rect, stream=buffer.getvalue())
                row['asset_evidence'] = {**evidence, 'body_png': str(png), 'body_sha256': sha(png)}
                item[f'{side}_pages'].append(len(doc))
    qpath = assets / 'questions.pdf'; spath = assets / 'solutions.pdf'
    qpdf.save(qpath, deflate=True)
    if len(spdf): spdf.save(spath, deflate=True)
    nq, ns = len(qpdf), len(spdf); qpdf.close(); spdf.close()
    database.init_db(); database.init_topics()
    pid = database.register_paper(str(qpath), str(spath) if ns else None)
    with database.get_connection() as c:
        c.execute('UPDATE papers SET paper_name=?,exam_type=?,source_institute=?,q_start=1,q_end=?,s_start=?,s_end=?,status=? WHERE id=?',
                  (paper_name, 'Textbook', cfg['book_source'], nq, 1 if ns else None, ns or None, 'uploaded', pid))
    commit = subprocess.check_output(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], text=True).strip()
    manifest = {'schema': 'ejee-paperlab-import/1', 'paper_id': pid, 'config': cfg,
                'upstream_commit': commit, 'question_pdf': str(qpath), 'solution_pdf': str(spath) if ns else None,
                'question_pdf_sha256': sha(qpath), 'solution_pdf_sha256': sha(spath) if ns else None,
                'paper_name': paper_name, **extra, 'items': items}
    dump(run / 'manifest.json', manifest)
    dump(run / 'progress.json', {'questions': {}, 'node3': {}})
    print(f'Prepared paper {pid}: {len(items)} questions, {nq} question pages, {ns} solution pages.', flush=True)


def clean_message(msg):
    content = msg.content
    if isinstance(content, list):
        content = [{**b, 'image_url': '[image omitted from log]'} if isinstance(b, dict) and b.get('type') == 'image_url' else b for b in content]
    return {'type': msg.type, 'content': content, 'tool_calls': getattr(msg, 'tool_calls', None),
            'tool_call_id': getattr(msg, 'tool_call_id', None)}


def source_heading(item):
    title = item['question_rows'][0]['title'].split(' · ', 1)[-1]
    return re.sub(r'\s*\(Exercise\)\s*$', '', title).strip()


def strip_problem_heading(tex, heading):
    """Remove a verified book heading, including inline headings, never the stem."""
    match = re.match(r'^\s*\d+(?:\.\d+)*[.)]?\s+', tex)
    offset = match.end() if match else 0
    rest = tex[offset:]
    normalize = lambda s: s.replace('’', "'").replace('‘', "'").strip()
    end = None
    if rest.startswith('\\textbf{'):
        depth, start = 1, len('\\textbf{')
        for i in range(start, len(rest)):
            if rest[i] == '{': depth += 1
            elif rest[i] == '}': depth -= 1
            if depth == 0:
                label = rest[start:i]
                label = re.sub(r'\$(?:\\ast|\\star|\*|∗|\s)+\$|[∗*]+', '', label)
                if normalize(label) == normalize(heading): end = i + 1
                break
    else:
        if normalize(rest[:len(heading)]) == normalize(heading):
            tail = rest[len(heading):]
            if not tail or tail[0].isspace() or tail[0] in '*∗': end = len(heading)
    if end is None: return tex
    body = rest[end:].lstrip()
    body = re.sub(r'^(?:\$(?:\\ast|\\star|\*|∗|\s)+\$|`?[∗*]+`?)\s*', '', body)
    return body.lstrip() if body.strip() else tex


def paragraph_range(number):
    """(A, B) for native group IDs like '31-34_paragraph', else None.

    Merged passage items keep per-sub Answer/Solution-for labels (31, 32
    ...), so the local-ID rewrite and equality checks must not touch them;
    range membership is the check instead.
    """
    m = re.fullmatch(r'(\d+)-(\d+)_paragraph', str(number))
    if not m or not int(m.group(1)) < int(m.group(2)) <= int(m.group(1)) + 12:
        return None
    return int(m.group(1)), int(m.group(2))


def strip_solution_heading(text, heading):
    """Remove one verified printed solution heading line (not the markers).

    Textbook solutions reprint "1.5. Damping" below the Solution-for
    heading. Only a standalone line whose title verifies against the source
    heading is removed; equation tags, prose and cross-references never
    match. Searches the first 10 lines; returns text unchanged if absent.
    """
    normalize = lambda s: s.replace('’', "'").replace('‘', "'").strip()
    lines = text.split('\n')
    for i, line in enumerate(lines[:10]):
        m = re.match(r'^\s*\d+(?:\.\d+)*[.)]?\s+(.*\S)\s*$', line)
        if not m:
            continue
        label = m.group(1)
        tm = re.match(r'^\\textbf\{(.*)\}$', label.strip())
        if tm:
            label = tm.group(1)
        label = re.sub(r'\$(?:\\ast|\\star|\*|∗|\s)+\$|[∗*]+', '', label)
        if normalize(label) == normalize(heading):
            del lines[i]
            return '\n'.join(lines)
    return text


_DISPLAY = re.compile(r'\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\begin\{(equation|align)\*?\}[\s\S]+?\\end\{\1\*?\}')


def _eqno_braced(tex):
    r"""Plain-TeX ``\eqno{X}`` -> ``\tag*{X}`` inside display math, printed text outside.

    KaTeX (the app's renderer) has no \eqno, so it shows as a red error.
    \tag* keeps the printed label exactly as written ("(1)", "...(3)"),
    without adding parentheses. A \eqno the model put after prose (outside
    any display) cannot carry a tag, so its label stays as plain text.
    """
    def braced(s, start):
        # index just past the group opened at s[start] == '{', or None
        depth = 0
        for i in range(start, len(s)):
            depth += {'{': 1, '}': -1}.get(s[i], 0)
            if depth == 0:
                return i + 1
        return None

    def rewrite(s, in_display):
        out, i = [], 0
        for m in re.finditer(r'\\eqno\s*(?=\{)', s):
            if m.start() < i:
                continue
            end = braced(s, m.end())
            if end is None:
                continue
            label = s[m.end() + 1:end - 1].strip()
            plain = re.fullmatch(r'\\text\{([^{}]*)\}', label)
            label = plain.group(1) if plain else label
            out.append(s[i:m.start()])
            out.append(r'\tag*{' + label + '}' if in_display else label)
            i = end
        out.append(s[i:])
        return ''.join(out)

    pieces, last = [], 0
    for m in _DISPLAY.finditer(tex):
        pieces.append(rewrite(tex[last:m.start()], False))
        pieces.append(rewrite(m.group(0), True))
        last = m.end()
    pieces.append(rewrite(tex[last:], False))
    return ''.join(pieces)


def normalize_rendering(tex, number=None):
    """Keep valid TeX while targeting the unchanged PaperLab/KaTeX bridge.

    With ``number`` (the fixed local question_number), the Answer label and
    every Solution-for heading are rewritten to it: the LLM sometimes echoes
    the printed source label (1.3) instead of the local ID (3), while the DB,
    folders and reader all key on the local ID. Only these two marker
    patterns are touched -- equation tags like (1.22) are never rewritten.
    """
    tex = re.sub(r'\\eqno\s*\(([^)\n]+)\)', lambda m: r'\tag{' + m[1] + '}', tex)
    tex = _eqno_braced(tex)
    # Tagged displays must be equation environments: \tag inside $$...$$
    # is rejected by real LaTeX (the compiled-image fallback fails) even
    # though the KaTeX bridge tolerates it. Single-tag displays only;
    # anything more complex is left for human review.
    def _split_relations(body):
        # 'M: .., \quad L: .., \quad T: .. \tag{N}' -> one env per relation,
        # tag travels with the last. Only when no relation holds an inner
        # comma; otherwise None (leave for human review).
        tagm = re.search(r'\\tag\{[^}]*\}\s*$', body)
        if not tagm or body.count('\\tag') != 1:
            return None
        core = body[:tagm.start()].strip().rstrip(',')
        parts = re.split(r',\s*\\quad\s*', core)
        if len(parts) >= 2 and all(',' not in p for p in parts):
            envs = ['\\begin{equation} ' + parts[0] + ', \\end{equation}']
            envs += ['\\begin{equation} ' + p + ', \\end{equation}'
                     for p in parts[1:-1]]
            envs += ['\\begin{equation} ' + parts[-1] + ' ' + tagm.group(0).strip()
                     + ' \\end{equation}']
            return '\n'.join(envs)
        return None

    def _tagged(m):
        body = m.group(1)
        split = _split_relations(body)
        if split is not None:
            return split
        if body.count('\\tag') != 1:
            return m.group(0)
        return '\\begin{equation} ' + body.strip() + ' \\end{equation}'
    tex = re.sub(r'\$\$([^\$]+?)\$\$', _tagged, tex)
    tex = re.sub(r'\\begin\{equation\}([\s\S]+?)\\end\{equation\}',
                 lambda m: _split_relations(m.group(1)) or m.group(0), tex)
    # Leading outside-chapter cross-reference clause ("As given below in
    # Exercise 1.9, show that ..."): it dangles in the app (no Exercise 1.9
    # exists here), so drop just that clause and capitalize the new start.
    # Fig/Eq/Table refs are kept (their targets are included).
    tex = re.sub(r'^(As (?:given|shown|stated|seen|proved|derived|found) '
                 r'(?:below|above) in (?:Exercise|Problem|Section|Chapter)\b[^,]*,\s*)([a-z])',
                 lambda m: m.group(2).upper(), tex)
    # Source margin key markers: the Answer line carries the key, so a
    # trailing "$v = 0$ \hfill \textbf{Ans.}" is boilerplate -- drop the
    # marker, keep the math/prose it annotates.
    tex = re.sub(r'(?:\\hfill[ \t]*)?\\textbf\{Ans\.?\}', '', tex)
    # Standalone figure-caption lines duplicate the \includegraphics plus
    # the in-sentence "as shown in Fig. N" reference -- drop them (full-line
    # match only, so prose references never match), including the form glued
    # to the figure's row break inside a center block.
    tex = re.sub(r'(?m)^[ \t]*Fig\.[~ \t]*\d[\d.]*\.?[ \t]*\r?\n?', '', tex)
    tex = re.sub(r'\\\\[ \t]*Fig\.[~ \t]*\d[\d.]*\.?[ \t]*\r?\n?(?=\\end\{center\})',
                 '', tex)
    if number is not None and paragraph_range(number) is None:
        lines = tex.split('\n')
        if lines and lines[0].startswith('\\textbf{Answer:'):
            lines[0] = re.sub(r'^(\\textbf\{Answer:\s*)[^)]*?(?=\))',
                               r'\g<1>' + str(number), lines[0], count=1)
            tex = '\n'.join(lines)
        # Solution-for heading shape drift (BIIT key-only cards): normalize ONLY
        # the heading shape+label to canonical
        # '\underline{\textbf{Solution for <number>}}', word for word
        # otherwise. Observed variants: missing \textbf
        # ('\underline{Solution for 5}'), hyphen ('Solution-for 5'),
        # Q-prefix ('Solution for Q.10'). Answer key lines untouched beyond
        # the label rewrite above; headings with extra trailing text inside
        # the braces are left for human review.
        def _canon_solution_for(m):
            return r'\underline{\textbf{Solution for ' + str(number) + '}}'
        tex = re.sub(r'\\underline\{(?:\\textbf\{)?Solution(?:-| )for\s+(?:Q\.?\s*)?\d+\s*\}\}?',
                     _canon_solution_for, tex)
    # Answer-line repair (idempotent): math/commands must live OUTSIDE the
    # \textbf{Answer: ...} braces. tex_to_markdown pairs $...$ before it
    # converts \textbf, so math inside the braces orphans a "{" in the
    # reader ("{Answer: 5) ...}"). Native extractor output never has math
    # there; close the bold after the label and keep the formula outside.
    lines = tex.split('\n')
    if lines and lines[0].startswith('\\textbf{Answer:'):
        m = re.match(r'^(\\textbf\{Answer:[^}]*?\))\s*(\$.*)\}$', lines[0])
        if m and '\\textbf' not in m.group(2):
            lines[0] = m.group(1) + '} ' + m.group(2)
            tex = '\n'.join(lines)
    escapes = {'\\': r'\textbackslash{}', '{': r'\{', '}': r'\}',
               '$': r'\$', '%': r'\%', '#': r'\#', '&': r'\&', '_': r'\_',
               '^': r'\textasciicircum{}', '~': r'\textasciitilde{}'}

    def program(match):
        # The native renderer strips verbatim environments, then Markdown
        # interprets code asterisks as emphasis and collapses line breaks.
        # A math array preserves rows and protects literal monospace text in
        # both KaTeX and LaTeX without requiring a PaperLab source change.
        rows = []
        for line in match[1].strip('\r\n').splitlines():
            code, marker, comment = line.partition('#')
            literal = lambda s: ''.join(escapes.get(ch,ch) for ch in s)
            rows.append(r'\texttt{' + literal(code.rstrip()) + '} & ' +
                        r'\texttt{' + literal(('#' + comment) if marker else '') + '}')
        return '\n\n$$\n' + r'\begin{array}{ll}' + '\n' + (' \\\\\n'.join(rows)) + '\n' + r'\end{array}' + '\n$$\n\n'
    return re.sub(r'\\begin\{verbatim\}\s*\n?(.*?)\\end\{verbatim\}', program, tex, flags=re.DOTALL)


def figure_edge_errors(pid, number, frozen=()):
    """Raster mode: block completion only where a crop edge CUTS content.

    An edge is a defect when ink touches it AND continues just outside the box
    in the source (a cut label/curve, or intruding text/figure). Edges that are
    merely tight, or lie on the source border, do not block. Figures frozen for
    human review are skipped. Returns (messages, names_with_defects).
    """
    import directory_manager
    from PIL import Image
    from crop_quality import edge_diagnosis
    folder = directory_manager.get_question_dir(pid, number) / 'figures'
    sidecar = folder / '_raster_boxes.json'
    boxes = json.loads(sidecar.read_text(encoding='utf-8')) if sidecar.exists() else {}
    errors, names = [], []
    for path in sorted(folder.glob('[qs]fig*.png')):
        frame = boxes.get(path.name)
        if path.name in frozen or frame is None:
            continue
        with Image.open(frame['body_png']) as source:
            cut = [e for e, state in edge_diagnosis(source.convert('RGB'), frame['box']).items()
                   if state == 'ink continues outside']
        if cut:
            names.append(path.name)
            errors.append(f'{path.name}: its {"/".join(cut)} edge(s) cut through content that continues '
                          'outside the box. Recrop with the same filename: EXPAND past a cut label/curve '
                          'of this diagram, or move INWARD into the blank gap if it is neighbouring text '
                          'or another figure.')
    return errors, names


def item_has_key(item):
    return any(r.get('answer') for r in item['question_rows'])


def validate_item(pid, number, has_solution, has_key=False):
    import directory_manager
    qdir = directory_manager.get_question_dir(pid, number)
    errors = []
    refs = set()
    for side, prefix in [('question', 'qfig'), ('solution', 'sfig')]:
        path = qdir / f'{side}.tex'
        if not path.is_file() or not path.read_text(encoding='utf-8').strip():
            errors.append(f'{side}.tex missing'); continue
        text = path.read_text(encoding='utf-8')
        if '[UNREADABLE]' in text: errors.append(f'{side}: unreadable content requires review')
        if side == 'solution' and has_key and not has_solution and not text.startswith('\\textbf{Answer:'):
            errors.append('source supplies an answer key: solution must open with the \\textbf{Answer:} key line')
        if side == 'solution' and has_solution:
            first = text.split('\n', 1)[0]
            if not first.startswith('\\textbf{Answer:'):
                errors.append('solution must open with an \\textbf{Answer:} key line')
            m = re.match(r'^\\textbf\{Answer:.*\}$', first)
            if m and ('$' in first or re.search(r'\\[a-zA-Z]', first[len('\\textbf{Answer:'):])) :
                errors.append('Answer line holds math/commands inside \\textbf braces; close the bold after the label')
            m = re.match(r'^\\textbf\{Answer:\s*([^)]*?)\)', first)
            prange = paragraph_range(number)
            if m and prange is not None:
                if not (m.group(1).strip().isdigit()
                         and prange[0] <= int(m.group(1).strip()) <= prange[1]):
                    errors.append(f'Answer sub-label {m.group(1).strip()!r} outside {number}')
            elif m and m.group(1).strip() != str(number):
                errors.append(f'Answer label {m.group(1).strip()!r} != local question_number {number!r}')
            for sm in re.finditer(r'\\underline\{(?:\\textbf\{)?Solution(?:-| )for\s+([^}]*?)\}?\}', text):
                if prange is not None:
                    if not (sm.group(1).strip().isdigit()
                             and prange[0] <= int(sm.group(1).strip()) <= prange[1]):
                        errors.append(f'Solution-for sub-label {sm.group(1).strip()!r} outside {number}')
                elif sm.group(1).strip() != str(number):
                    errors.append(f'Solution-for {sm.group(1).strip()!r} != local question_number {number!r}')
        if side == 'solution' and has_key and not has_solution:
            # Key-only solutions legitimately omit the heading; but a PRESENT
            # heading with a wrong label must fail loudly, never pass silently.
            prange = paragraph_range(number)
            for sm in re.finditer(r'\\underline\{(?:\\textbf\{)?Solution(?:-| )for\s+([^}]*?)\}?\}', text):
                if prange is not None:
                    if not (sm.group(1).strip().isdigit()
                             and prange[0] <= int(sm.group(1).strip()) <= prange[1]):
                        errors.append(f'Solution-for sub-label {sm.group(1).strip()!r} outside {number}')
                elif sm.group(1).strip() != str(number):
                    errors.append(f'Solution-for {sm.group(1).strip()!r} != local question_number {number!r}')

        if '\\eqno' in text:
            errors.append(f'{side}: \\eqno is not rendered by the app (shows as an error); use \\tag in an equation environment')
        if any('\\tag' in m.group(1) for m in re.finditer(r'\$\$([\s\S]+?)\$\$', text)):
            errors.append(f'{side}: \\tag inside $$...$$ breaks the compiled-image fallback; use an equation environment')
        if side == 'question' and re.search(r'which one is it|which of the following', text, re.IGNORECASE) \
                and '\\begin{enumerate}' not in text:
            errors.append('question offers candidate answers but has no enumerate; use one \\item per option')
        if side == 'solution' and has_solution and (
                ('No solution provided.' in text
                 and not re.search(r'\\textbf\{Answer:', text))
                or len(text.strip()) < 50):
            errors.append('Mapped solution was replaced by placeholder/empty text')
        for file in re.findall(r'\\includegraphics(?:\[[^\]]*\])?\{figures/([^}]+)\}', text):
            if not re.fullmatch(prefix + r'\d+\.png', file): errors.append(f'Invalid side/filename: {file}')
            if not (qdir / 'figures' / file).is_file(): errors.append(f'Missing figure {file}')
            refs.add(file)
    for path in (qdir / 'figures').glob('*.png'):
        if path.name not in refs: errors.append(f'Unreferenced figure {path.name}')
    return errors


def extract_item(manifest, item, cfg, run):
    from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
    from langgraph.types import Command
    import database
    import tools_extractor as tools
    from llm import get_llm, invoke_with_retry
    pid, number = manifest['paper_id'], item['number']
    # These canvases are 200 dpi raster sources, unlike upstream vector PDFs.
    # Keep its crop algorithms but do not save a 600 dpi upsample of the pixels.
    tools._SAVE_DPI = 200
    selected = [tools.get_page_image, tools.assisted_crop, tools.exact_crop, tools.submit_question, tools.submit_solution]
    if cfg.get('raster_exact_crop', False):
        from raster_crop import make_exact_crop, make_page_image
        selected[2] = make_exact_crop(manifest, tools)
        selected[0] = make_page_image(manifest, tools, run)
    paired = cfg.get('paired_submit', cfg.get('raster_exact_crop', False))
    if paired:
        from cost_controls import make_submit_pair
        selected = selected[:3] + [make_submit_pair()]
    from extraction_contract import bind_descriptions, build_prompt
    selected = bind_descriptions(selected, cfg)
    by_name = {t.name: t for t in selected}
    prompt = build_prompt(cfg)
    allowed = {manifest['question_pdf']: item['question_pages']}
    if manifest['solution_pdf']: allowed[manifest['solution_pdf']] = item['solution_pages']
    metadata = {'paper_id': pid, 'question_number': number, 'source_label': item['question_rows'][0]['title'],
                'source_groups': item.get('groups', [item['group']]) if item.get('merged') else [item['group']],
                'split_problem': item.get('kind') == 'merged',
                'allowed_pages': allowed, 'has_mapped_solution': bool(item['solution_rows']),
                'source_answers': [r['answer'] for r in item['question_rows'] if r['answer']],
                'source_question_text': [r['question'] for r in item['question_rows'] if r['question']],
                'source_solution_text': [r['solution'] for r in item['question_rows'] if r['solution']],
                 'source_qtype': [r['qtype'] for r in item['question_rows'] if r['qtype']]}
    from extraction_contract import page_geometry
    metadata['page_geometry'] = page_geometry(manifest, item)
    metadata['reviewed_diagrams'] = reuse_reviewed(cfg, item, pid, number, run)
    messages = [SystemMessage(content=prompt), HumanMessage(content=json.dumps(metadata, ensure_ascii=False))]
    # Existing resource mapping supplies the images immediately; no searching/indexing calls.
    for side in ['question', 'solution']:
        for row, page in zip(item[f'{side}_rows'], item[f'{side}_pages']):
            messages.append(HumanMessage(content=[{'type': 'text', 'text': f'{side.upper()} page {page}, resource {row["id"]}; already body-cropped, no key-sheet assumption.'},
                                                    tools.img_block(row['asset_evidence']['body_png'], tools.PAGE_PX)]))
    # Raster mode: independent figures may be cropped in the same turn (each
    # call is still budgeted and executed in order); 20-turn ceiling unchanged.
    llm = get_llm().bind_tools(selected, parallel_tool_calls=bool(cfg.get('parallel_crops', cfg.get('raster_exact_crop', False))))
    saved = set(); t0 = time.time()
    from crop_budget import CropBudget, CropBudgetExceeded
    crop_budget = CropBudget(cfg.get('max_crop_calls_per_figure', 8))
    log = run / 'traces' / f'{number}.json'
    from submission_guard import normalize_figure_references, guard_saved_submission
    from cost_controls import prune_previews

    def save(kind, latex, qtype=None):
        # Same heading strip, rendering normalization, native validator/saver
        # and post-save guard as the separate submit tools.
        name = 'submit_question' if kind == 'question' else 'submit_solution'
        strip = strip_problem_heading if kind == 'question' else strip_solution_heading
        latex = normalize_figure_references(normalize_rendering(strip(latex, source_heading(item)), number))
        native_args = {'paper_id': pid, 'question_number': number, 'latex_content': latex}
        if kind == 'question':
            native_args['qtype'] = qtype or 'unknown'
        result = str(getattr(tools, name).invoke(native_args))
        if result == 'saved':
            guard_saved_submission(pid, number, kind, latex)
            saved.add(name)
        return result

    frozen, gate_rounds = set(), 0
    review_file = run / 'review_required' / f'{number}.json'
    if review_file.exists():
        # A retry starts a fresh attempt: archive the old record (not read by
        # verify) so stale holds from a failed attempt don't linger.
        review_file.rename(review_file.with_name(f'{number}.attempt-{int(time.time())}.bak'))

    def hold_for_review(filename, reason):
        # The figure is kept as-is but BLOCKS verify/merge until a human
        # approves it; the transcription is not thrown away.
        frozen.add(filename)
        record = json.loads(review_file.read_text(encoding='utf-8')) if review_file.exists() else {
            'question': number, 'approved': False, 'figures': {}}
        record.setdefault('figures', {})[filename] = reason
        record['reason'] = '; '.join(record.get('unreadable', []) + [f'{k}: {v}' for k, v in record['figures'].items()])
        dump(review_file, record)

    max_turns = cfg.get('max_turns_per_question', 20)
    reserve = cfg.get('submit_reserve_turns', 4)
    closing_sent = False
    for turn in range(max_turns):
        if turn >= max_turns - reserve and len(saved) < 2 and not closing_sent:
            closing_sent = True
            # Never lose a transcription to figure polishing: the last turns
            # are reserved for saving; current crops are held for review.
            messages.append(HumanMessage(content=(
                'Turn budget nearly used. Cropping is now closed: every figure keeps its current '
                'crop and is held for human review. Call submit_pair NOW with the complete '
                'question and solution, referencing the figures you already saved.')))
        if cfg.get('prune_previews', False):
            # Off by default: editing earlier messages breaks the provider's
            # prompt cache, so the whole tail is re-billed at full price.
            # Kept old previews are cached (~2% of input price) instead.
            prune_previews(messages)
        response = invoke_with_retry(llm, messages)
        usage = response.usage_metadata or {}
        database.log_token_usage(pid, 'extractor', input_tokens=usage.get('input_tokens', 0),
                                 cache_read=(usage.get('input_token_details') or {}).get('cache_read', 0),
                                 output_tokens=usage.get('output_tokens', 0),
                                 reasoning_tokens=(usage.get('output_token_details') or {}).get('reasoning', 0))
        if not response.tool_calls and isinstance(response.content, str):
            from cost_controls import recover_text_tool_calls
            from langchain_core.messages import AIMessage
            recovered = recover_text_tool_calls(response.content, set(by_name))
            if recovered:
                # Provider emitted the call as text: replay it as a normal
                # structured call through the same validators (logged).
                response = AIMessage(content='[recovered text-form tool call]', tool_calls=[
                    {'name': c['name'], 'args': c['args'], 'id': f'recovered-{turn}-{i}', 'type': 'tool_call'}
                    for i, c in enumerate(recovered)], usage_metadata=response.usage_metadata)
        messages.append(response)
        for call in response.tool_calls or []:
            args = dict(call['args']); name = call['name']
            if name in ('assisted_crop', 'exact_crop') and turn >= max_turns - reserve:
                hold_for_review(args.get('output_filename', '?'), 'cropping closed: turn budget reserved for saving')
                messages.append(ToolMessage(
                    content='Cropping is closed (turn budget reserved for saving). The current crop is held '
                            'for human review. Call submit_pair now.', tool_call_id=call['id']))
                continue
            if name in ('assisted_crop', 'exact_crop'):
                try:
                    crop_budget.check(args)
                except CropBudgetExceeded as exc:
                    hold_for_review(args.get('output_filename', '?'), f'crop limit reached: {exc}')
                    messages.append(ToolMessage(
                        content=f'Crop limit reached for {args.get("output_filename")}: it is now FROZEN '
                                'and held for human review. Do not crop it again. Keep it referenced and '
                                'finish the transcription with submit_pair.',
                        tool_call_id=call['id']))
                    continue
            try:
                if name not in by_name: raise ValueError('Tool not allowed')
                if name == 'submit_question':
                    args['latex_content'] = strip_problem_heading(args['latex_content'], source_heading(item))
                if name == 'submit_solution':
                    args['latex_content'] = strip_solution_heading(args['latex_content'], source_heading(item))
                if name in ('submit_question', 'submit_solution'):
                    args['latex_content'] = normalize_rendering(args['latex_content'], number)
                    from submission_guard import normalize_figure_references
                    args['latex_content'] = normalize_figure_references(args['latex_content'])
                if 'paper_id' in args and args['paper_id'] != pid: raise ValueError('Wrong paper ID')
                if 'question_number' in args and str(args['question_number']) != number: raise ValueError('Wrong question number')
                if 'pdf_path' in args:
                    if args['pdf_path'] not in allowed or args.get('page_number') not in allowed[args['pdf_path']]:
                        raise ValueError('PDF/page is outside this mapped question')
                if name in ('assisted_crop', 'exact_crop'):
                    prefix = 'qfig' if args['pdf_path'] == manifest['question_pdf'] else 'sfig'
                    if not re.fullmatch(prefix + r'\d+\.png', args.get('output_filename', '')):
                        raise ValueError('Use the correct side and stable qfigN.png/sfigN.png filename')
                if name == 'submit_pair':
                    q = save('question', args['question_latex'], args.get('qtype'))
                    s_res = save('solution', args['solution_latex']) if q == 'saved' else 'not attempted (question not saved)'
                    result = f'question: {q}\nsolution: {s_res}'
                elif name in ('get_page_image', 'assisted_crop', 'exact_crop'):
                    result = by_name[name].invoke({'name': name, 'args': args, 'id': call['id'], 'type': 'tool_call'})
                else:
                    result = by_name[name].invoke(args)
                    if name in ('submit_question', 'submit_solution') and str(result) == 'saved':
                        from submission_guard import guard_saved_submission
                        guard_saved_submission(pid, number,
                                               'question' if name == 'submit_question' else 'solution',
                                               args['latex_content'])
                if isinstance(result, Command): messages.extend(result.update.get('messages', []))
                else:
                    messages.append(ToolMessage(content=str(result), tool_call_id=call['id']))
                    if name in ('submit_question', 'submit_solution') and str(result) == 'saved': saved.add(name)
            except Exception as exc:
                messages.append(ToolMessage(content=f'Error: {type(exc).__name__}: {exc}', tool_call_id=call['id']))
        dump(log, {'turns': turn+1, 'elapsed_sec': time.time()-t0, 'messages': [clean_message(m) for m in messages]})
        if len(saved) == 2:
            errors = validate_item(pid, number, bool(item['solution_rows']), item_has_key(item))
            # [UNREADABLE] is the REQUIRED answer to illegible source: the model
            # cannot fix it, so hold the question for a human (verify still
            # blocks merge) instead of looping on it.
            unreadable = [e for e in errors if 'unreadable content requires review' in e]
            if unreadable:
                errors = [e for e in errors if e not in unreadable]
                record = json.loads(review_file.read_text(encoding='utf-8')) if review_file.exists() else {
                    'question': number, 'approved': False, 'figures': {}}
                record['unreadable'] = unreadable
                record['reason'] = '; '.join(unreadable + [f'{k}: {v}' for k, v in record.get('figures', {}).items()])
                dump(review_file, record)
            edge_msgs, edge_names = (figure_edge_errors(pid, number, frozen)
                                     if cfg.get('raster_exact_crop', False) else ([], []))
            max_rounds = cfg.get('max_edge_gate_rounds', 2)
            if not errors and (not edge_msgs or gate_rounds >= max_rounds or turn >= max_turns - reserve):
                for name in edge_names:
                    hold_for_review(name, f'edge still cuts content after {gate_rounds} correction round(s)')
                import directory_manager
                qtext = (directory_manager.get_question_dir(pid, number) / 'question.tex').read_text(encoding='utf-8').lstrip()
                if re.match(r'[a-z]', qtext):
                    # A faithful transcription of a card that begins mid-sentence:
                    # the opening is missing from the SOURCE. Keep it, but a human
                    # must confirm (verify blocks merge until approved).
                    record = json.loads(review_file.read_text(encoding='utf-8')) if review_file.exists() else {
                        'question': number, 'approved': False, 'figures': {}}
                    record['source_note'] = 'question starts mid-sentence: the source card may be missing its opening'
                    record['reason'] = '; '.join(filter(None, [record.get('reason'), record['source_note']]))
                    dump(review_file, record)
                return {'ok': True, 'turns': turn+1, 'elapsed_sec': round(time.time()-t0, 2),
                        'figures_held_for_review': sorted(frozen)}
            if not errors:
                gate_rounds += 1
            messages.append(HumanMessage(content='Completion check failed; correct with same IDs: '
                                         + '; '.join(errors + edge_msgs)))
        elif not response.tool_calls:
            messages.append(HumanMessage(content=(
                'Finish this mapped item with one submit_pair call (question_latex and solution_latex).'
                if paired else
                'Finish this mapped item by calling both submit_question and submit_solution.')
                + ' Do not invent missing solutions.'))
    raise RuntimeError(f'{number}: turn limit reached; trace saved for review')


def extract(cfg, run):
    import database
    manifest = json.loads((run / 'manifest.json').read_text(encoding='utf-8'))
    progress = json.loads((run / 'progress.json').read_text(encoding='utf-8'))
    pid = manifest['paper_id']; t0 = time.time()
    database.set_paper_status(pid, 'extracting')
    for item in manifest['items']:
        number = item['number']
        if progress['questions'].get(number, {}).get('ok') and not validate_item(pid, number, bool(item['solution_rows']), item_has_key(item)):
            continue
        print(f'Extracting {number} ({len(item["solution_rows"])} solution parts)', flush=True)
        try:
            progress['questions'][number] = extract_item(manifest, item, cfg, run)
        except Exception as exc:
            # One hard question must not block the rest of the part: record
            # it (trace + review record already saved) and continue.
            progress['questions'][number] = {'ok': False, 'error': f'{type(exc).__name__}: {exc}'}
        dump(run / 'progress.json', progress)
        print(f'{number}: {progress["questions"][number]}', flush=True)
    failed = [n for n, r in progress['questions'].items() if not r.get('ok')]
    if failed:
        database.set_paper_status(pid, 'failed', f'{len(failed)} question(s) need review: {failed}', time.time()-t0)
        print(f'Extraction finished with {len(failed)} question(s) needing review: {failed}. '
              'Re-run extract to retry only those.', flush=True)
        raise SystemExit(2)
    elapsed = sum(r.get('elapsed_sec', 0) for r in progress['questions'].values())
    database.set_paper_status(pid, 'done', elapsed_sec=elapsed)
    database.mark_paper_archived(pid)
    print(f'Extraction complete: {len(manifest["items"])} questions. Run classify next.', flush=True)


def is_abstention(report):
    """Node 3 answered but could not tag fully: no topic (e.g. 'TOPICS: NONE'
    with a suggestion) or no difficulty ('DIFFICULTY: NONE'). Not an error:
    with ``allow_untagged`` the question is published untagged and lands in
    PaperLab's Tagging Inbox for a person to tag."""
    return bool(report) and not report.get('ok') and not report.get('errors') and bool(report.get('raw_reply')) \
        and (not report.get('codes') or not report.get('difficulty'))


def valid_classification(report):
    # Upstream explicitly permits no matching topic with a new-topic suggestion.
    return bool(report.get('difficulty') and (report.get('codes') or report.get('suggestion')) and not report.get('errors'))


def reviewed_crops(cfg, run=None):
    """Human-reviewed rectangles: the config's shared file plus this run's repairs."""
    crops = json.loads((ROOT / cfg['reviewed_crops']).read_text(encoding='utf-8')) if cfg.get('reviewed_crops') else []
    local = Path(run) / 'reviewed_crops.json' if run else None
    if local and local.is_file():
        crops = json.loads(local.read_text(encoding='utf-8')) + crops  # run repairs take precedence
    return crops


def node3_inputs_hash() -> dict:
    """Fingerprint everything upstream classification depends on.

    Seed rows, teaching order, the topic prompt, and the upstream commit:
    changes can affect numbering, primary rank or parsing, so cached auto tags
    must not survive it (re-running stale tags would silently misfile
    questions). Best-effort commit (None outside git); the file hashes are
    the load-bearing part.
    """
    files = {
        'seed': REPO / 'topics_seed.json',
        'teaching_order': REPO / 'topics_teaching_order.json',
        'prompt': REPO / 'prompts' / 'topic_prompt.md',
    }
    meta = {k: sha(p) if p.is_file() else None for k, p in files.items()}
    try:
        meta['upstream'] = subprocess.check_output(
            ['git', '-C', str(REPO), 'rev-parse', 'HEAD'],
            text=True).strip()
    except Exception:
        meta['upstream'] = None
    return meta


def reuse_reviewed(cfg, item, pid, number, run=None):
    """Reuse only reviewed isolated rectangles whose source pixel hash still matches."""
    from PIL import Image
    import directory_manager
    reused = []
    for crop in reviewed_crops(cfg, run):
        if crop['group'] not in item.get('groups', [item['group']]): continue
        for side in ('question', 'solution'):
            if not crop['filename'].startswith('qfig' if side == 'question' else 'sfig'): continue
            for row,page in zip(item[f'{side}_rows'], item[f'{side}_pages']):
                ev = row['asset_evidence']
                if ev['body_sha256'] != crop['source_body_sha256']: continue
                if sha(ev['body_png']) != crop['source_body_sha256']: raise ValueError('Reviewed diagram source changed')
                with Image.open(ev['body_png']) as im:
                    b = crop['source_pixel_box']
                    if not (0 <= b[0] < b[2] <= im.width and 0 <= b[1] < b[3] <= im.height): raise ValueError('Invalid reviewed diagram bounds')
                    qdir = directory_manager.ensure_question_dir(pid, number)
                    im.crop(b).save(qdir / 'figures' / crop['filename'])
                reused.append({'filename': crop['filename'], 'side': side, 'page': page, 'resource_id': row['id'], 'review': crop['reason']})
    return reused


def classify(cfg, run):
    # Execute upstream Node 3 unchanged. No EJEE difficulty/tags enter this stage.
    import config
    import database
    from run_topics import build_topic_reference, classify_question
    manifest = json.loads((run / 'manifest.json').read_text(encoding='utf-8'))
    progress = json.loads((run / 'progress.json').read_text(encoding='utf-8'))
    primary_mode = config.topic_primary_mode()
    topic_reference = build_topic_reference()
    meta = {**node3_inputs_hash(), 'primary_mode': primary_mode}
    if progress.get('node3_meta') not in (None, meta):
        # Classification inputs or ranking changed under a cached classification:
        # cached auto tags would misfile questions, so drop them and redo.
        # Explicit and loud (re-running costs API calls, keeping stale tags
        # costs correctness).
        print(f'Node 3 inputs changed (was {progress["node3_meta"]}); '
              f'discarding {len(progress.get("node3", {}))} cached classification(s).', flush=True)
        progress['node3'] = {}
    progress['node3_meta'] = meta
    skipped, failed = [], []
    for item in manifest['items']:
        number = item['number']
        if not progress['questions'].get(number, {}).get('ok'):
            skipped.append(number)  # extraction under review; classify the rest
            continue
        previous = progress['node3'].get(number, {})
        if valid_classification(previous):
            previous['ok'] = True
            dump(run / 'progress.json', progress)
            continue
        report = classify_question(manifest['paper_id'], number, topic_reference, primary_mode=primary_mode)
        report['ok'] = bool(report.get('ok') and valid_classification(report))
        progress['node3'][number] = report
        dump(run / 'progress.json', progress)
        print(f'Node 3 {number}: {report}', flush=True)
        if not report['ok']:
            failed.append(number)
        time.sleep(1)
    if skipped or failed:
        print(f'Node 3 skipped (extraction under review): {skipped}; incomplete: {failed}. '
              'Re-run classify after fixing; finished questions are not re-billed.', flush=True)
        raise SystemExit(2)


def figures(cfg, run):
    """Export accepted raster boxes from original pixels, without PDF upsampling."""
    import math
    from PIL import Image
    import directory_manager
    manifest = json.loads((run / 'manifest.json').read_text(encoding='utf-8'))
    exported = []
    for item in manifest['items']:
        trace = json.loads((run / 'traces' / f'{item["number"]}.json').read_text(encoding='utf-8'))
        pending, accepted = [], {}
        for message in trace['messages']:
            if message['type'] == 'ai': pending.extend(message.get('tool_calls') or [])
            elif message['type'] == 'tool' and pending:
                call = pending.pop(0)
                if call['name'] not in ('assisted_crop', 'exact_crop'): continue
                text = message['content']
                match = re.search(r'final box: (\[[^\]]+\])', text)
                if match and not str(text).startswith('Error:'):
                    accepted[call['args']['output_filename']] = (call, json.loads(match[1]), text)
        qdir = directory_manager.get_question_dir(manifest['paper_id'], item['number'])
        evidence = {}
        for filename, (call, box, text) in accepted.items():
            args = call['args']
            side = 'question' if args['pdf_path'] == manifest['question_pdf'] else 'solution'
            index = item[f'{side}_pages'].index(args['page_number'])
            source = item[f'{side}_rows'][index]['asset_evidence']
            with Image.open(source['body_png']) as im:
                x,y,w,h = box
                # Tool replies round normalized coordinates. Preserve a one-unit
                # safety margin so that rounding cannot remove an accepted label.
                pad = 0 if cfg.get('raster_exact_crop', False) and call['name'] == 'exact_crop' else 1
                px = [max(0, math.floor((x-pad)*im.width/1000)), max(0, math.floor((y-pad)*im.height/1000)),
                      min(im.width, math.ceil((x+w+pad)*im.width/1000)), min(im.height, math.ceil((y+h+pad)*im.height/1000))]
                review = next((r for r in reviewed_crops(cfg, run) if r['group'] in item.get('groups', [item['group']]) and r['filename'] == filename and r['source_body_sha256'] == source['body_sha256']), None)
                if review: px = review['source_pixel_box']
                cropped = im.crop(px)
                dest = qdir / 'figures' / filename
                cropped.save(dest, format='PNG')
                evidence[filename] = {'source_body': source['body_png'], 'source_sha256': source['body_sha256'],
                                      'tool_final_box': box, 'source_pixel_box': px, 'size': list(cropped.size),
                                      'sha256': sha(dest), 'method': 'lossless source-pixel crop; one normalized unit safety margin'}
                if review: evidence[filename]['review_override'] = review
        for reused in reuse_reviewed(cfg, item, manifest['paper_id'], item['number'], run):
            crop = next(r for r in reviewed_crops(cfg, run) if r['group'] in item.get('groups', [item['group']]) and r['filename'] == reused['filename'])
            source = next(r['asset_evidence'] for r in item[f'{reused["side"]}_rows'] if r['id'] == reused['resource_id'])
            dest = qdir / 'figures' / reused['filename']
            with Image.open(dest) as im: size = list(im.size)
            evidence[reused['filename']] = {**evidence.get(reused['filename'], {}),
                'source_body': source['body_png'], 'source_sha256': source['body_sha256'],
                'source_pixel_box': crop['source_pixel_box'], 'size': size, 'sha256': sha(dest),
                'method': 'reviewed source-pixel crop reused by exact image hash', 'review_override': crop}
        if evidence:
            dump(qdir / 'figures' / '_import_provenance.json', evidence)
            exported.extend({'question': item['number'], 'filename': k, **v} for k,v in evidence.items())
    dump(run / 'figure_export.json', exported)
    print(f'Exported {len(exported)} accepted figures from original pixels without upsampling.', flush=True)
    if cfg.get('native_figure_cleanup', False):
        from figure_cleanup import cleanup_run
        report = cleanup_run(run)
        print(f'Guarded native cleanup: {sum(r["changed"] for r in report)} safe trims; '
              f'{sum(r["review_required"] for r in report)} figures flagged for review.',
              flush=True)
    if cfg.get('raster_exact_crop', False):
        from crop_quality import audit_run
        report = audit_run(run)
        print(f'Raster crop audit: {len(report)} crops; '
              f'{sum(r["review_required"] for r in report)} require review.',
              flush=True)


def pack(cfg, run):
    """Normalize legacy pilot IDs and renderer-sensitive heading stars in DATA only."""
    import database
    import directory_manager
    manifest = json.loads((run / 'manifest.json').read_text(encoding='utf-8'))
    progress = json.loads((run / 'progress.json').read_text(encoding='utf-8'))
    changes = []
    pattern = re.compile(cfg['group_pattern']) if cfg.get('group_pattern') else None
    for item in manifest['items']:
        old = item['number']
        # Book mode: local 1..N IDs are assigned by the frozen plan.
        if pattern is None or len(item.get('groups', [item['group']])) > 1:
            # Explicit merge: the local number came from merge_groups and is
            # already on disk/DB; never re-derive it from a single group.
            new = item['number']
        else:
            new = str(int(pattern.fullmatch(item['group'])['number']))
        item.setdefault('source_number', old)
        qdir = directory_manager.get_question_dir(manifest['paper_id'], old)
        if old != new:
            dest = directory_manager.get_question_dir(manifest['paper_id'], new)
            if dest.exists(): raise ValueError(f'Target ID already exists: {new}')
            qdir.rename(dest)
            with database.get_connection() as c:
                c.execute('UPDATE questions SET question_number=?,latex_folder=? WHERE paper_id=? AND question_number=?',
                          (new, str(dest), manifest['paper_id'], old))
            for phase in ('questions', 'node3'):
                if old in progress[phase]: progress[phase][new] = progress[phase].pop(old)
            trace = run / 'traces' / f'{old}.json'
            if trace.exists(): trace.rename(run / 'traces' / f'{new}.json')
            item['extraction_number'] = old
            item['number'] = new
            qdir = dest
            changes.append({'kind': 'local_question_id', 'source_number': old, 'target_number': new,
                            'reason': 'One chapter per paper: local numeric IDs sort correctly in unchanged upstream reader. Printed source labels and tool traces remain verbatim.'})
        for side in ('question', 'solution'):
            path = qdir / f'{side}.tex'
            if not path.exists(): continue
            before = path.read_text(encoding='utf-8')
            # A printed difficulty star inside textbf becomes *** in upstream's
            # Markdown bridge. Move only that symbol outside bold, as math.
            if side == 'question':
                after = normalize_rendering(strip_problem_heading(before, source_heading(item)),
                                            item['number'])
            else:
                after = normalize_rendering(strip_solution_heading(before, source_heading(item)),
                                            item['number'])
            if after != before:
                from tools_extractor import verify_latex_syntax
                verdict = verify_latex_syntax.invoke({"latex_string": after})
                if verdict != 'Valid':
                    raise ValueError(f'pack produced invalid LaTeX for {new}/{side}: {verdict}')
                path.write_text(after, encoding='utf-8')
                changes.append({'kind': 'content_and_rendering_normalization', 'question': new, 'side': side,
                                'before_sha256': hashlib.sha256(before.encode()).hexdigest(), 'after_sha256': sha(path),
                                'reason': 'Keep statement-only questions and solutions; normalize equation tags and preserve literal code rows for the unchanged native renderer.'})
    dump(run / 'manifest.json', manifest)
    dump(run / 'progress.json', progress)
    previous = json.loads((run / 'data_normalizations.json').read_text(encoding='utf-8')) if (run / 'data_normalizations.json').exists() else []
    # figure_export.json keys pre-pack (extraction) numbers: remap to local IDs.
    renames = {it.get('extraction_number', it['number']): it['number'] for it in manifest['items']}
    fx = run / 'figure_export.json'
    if fx.exists():
        exported = json.loads(fx.read_text(encoding='utf-8'))
        for entry in exported:
            entry['question'] = renames.get(entry.get('question'), entry.get('question'))
        fx.write_text(json.dumps(exported, indent=2, ensure_ascii=False), encoding='utf-8')
    dump(run / 'data_normalizations.json', previous + changes)
    if changes and any(progress.get('node3', {}).values()):
        print('WARNING: pack modified .tex after classify ran; re-run classify to refresh Node 3 tags.', flush=True)
    print(f'Packed chapter with {len(changes)} recorded data normalizations; no application source edits.', flush=True)


def merge(cfg, run, target_db=None, target_outputs=None):
    """Step 2: copy one verified run into the main archive database.

    Step 1 (staging) already happened: prepare/extract/figures/classify/pack
    all wrote to the run's own temp database (runs/<name>/paperlab.db); the
    production database was never opened. Merge promotes that staged result:

    1. Re-runs verify() fresh -- anything failing never reaches the target.
    2. Refuses when the target IS the run DB, when this run was already
       merged into the same target, or when the PDF hash already exists
       there (native DuplicatePaperError semantics, reported not raised).
    3. Backs the target up beside itself (<name>.pre-merge-<utc>.bak).
    4. Copies the paper row (new id), every question row (new ids, latex
       folders rewritten to the target Outputs tree and copied), all
       topic links (codes preserved; seed ensured on target), usage rows
       and both source PDFs -- in one transaction, then re-checks
       integrity, foreign keys and counts before committing the receipt.

    IDs are always regenerated by the target (AUTOINCREMENT); only
    question_number strings, topic codes and file contents carry over.

    Since the universal bundle format exists, this exports the verified run
    and merges through ``paperlab_bundle.merge_bundle`` -- one merger for
    every importer, with backup, checksum validation and rollback.
    """
    import sys
    sys.path.insert(0, str(REPO))
    from paperlab_bundle import merge_bundle
    bundle = export_bundle(cfg, run)  # verify() inside: fail first, merge never
    manifest = json.loads((run / 'manifest.json').read_text(encoding='utf-8'))
    target = target_db or cfg.get('merge_target_db')
    if not target:
        raise ValueError('Merge requires an explicit --target-db')
    if Path(target).resolve().is_relative_to(run.resolve()):
        raise ValueError('Merge target must be outside the staging run')
    output_arg = target_outputs or cfg.get('merge_target_outputs')
    if output_arg and Path(output_arg).resolve().is_relative_to(run.resolve()):
        raise ValueError('Merge target Outputs must be outside the staging run')
    already = manifest.get('merged') or {}
    if already.get('target_db') == str(Path(target).resolve()):
        raise ValueError(f'Already merged into {target} as paper {already["paper_id"]} '
                         f'at {already["at"]} (backup {already["backup"]}).')
    receipt = merge_bundle(bundle['path'], target, output_arg)
    manifest['merged'] = {'target_db': str(Path(target).resolve()),
                          'paper_id': receipt['papers'][0]['archive_paper'],
                          'at': receipt['merged'], 'backup': receipt['backup'],
                          'bundle': bundle['path']}
    dump(run / 'manifest.json', manifest)
    dump(run / 'merge.json', receipt)
    print(f'Merged paper {manifest["paper_id"]} -> {target} as paper {receipt["papers"][0]["archive_paper"]}: '
          f'{receipt["papers"][0]["questions"]} questions. Backup: {receipt["backup"]}.', flush=True)
    return receipt


def repair(cfg, run, picks=None, by=None):
    """Fix held/flagged figures WITHOUT model calls, from measured options.

    No picks: writes ``repair/<Q>__<fig>.png`` candidate sheets and
    ``repair/candidates.json`` (current crop + per-edge in/out steps + the
    combined expand/shrink), each with its edge diagnosis. With picks
    (``{"10/sfig1.png": ["bottom-out"], "1/qfig1.png": ["top-in", "left-out"]}``,
    applied in order, each measured from the previous result) the chosen
    rectangle is recorded in ``reviewed_crops.json`` (source-hash bound, so it
    survives re-runs) and the figures are re-exported from original pixels.
    The new PNG must still be approved (its hash changed).
    """
    from PIL import Image, ImageDraw
    from crop_quality import audit_run, edge_diagnosis, edge_steps, gap_suggestions
    manifest = json.loads((run / 'manifest.json').read_text(encoding='utf-8'))
    pid = manifest['paper_id']
    by_number = {str(i['number']): i for i in manifest['items']}

    def options(src, box):
        found = dict(edge_steps(src, box))
        found.update(gap_suggestions(src, box))
        return found

    def frame(number, filename):
        prov = run / 'Outputs' / str(pid) / number / 'figures' / '_import_provenance.json'
        evidence = json.loads(prov.read_text(encoding='utf-8')).get(filename) if prov.is_file() else None
        if not evidence:
            raise ValueError(f'{number}/{filename}: no exported provenance; run the figures phase first')
        return evidence

    if picks:
        if not by:
            raise ValueError('repair --pick needs --by (who chose the rectangle)')
        store = run / 'reviewed_crops.json'
        reviewed = json.loads(store.read_text(encoding='utf-8')) if store.is_file() else []
        for key, steps in picks.items():
            number, filename = key.split('/', 1)
            evidence = frame(number, filename)
            with Image.open(evidence['source_body']) as image:
                src = image.convert('RGB')
            box = list(evidence['source_pixel_box'])
            for step in steps:
                found = options(src, box)
                if step not in found:
                    raise ValueError(f'{key}: option {step!r} not available here; have {sorted(found)}')
                box = found[step]
            item = by_number[number]
            entry = {'group': item['group'], 'filename': filename, 'source_body_sha256': sha(evidence['source_body']),
                     'source_pixel_box': box, 'reason': f'repaired by {by}: {"+".join(steps)} (measured options)',
                     'repaired_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
            reviewed = [r for r in reviewed if not (r['group'] == entry['group'] and r['filename'] == filename)] + [entry]
            print(f'{key}: {"+".join(steps)} -> {box}; edges now {edge_diagnosis(src, box) or "clean"}', flush=True)
        dump(store, reviewed)
        figures(cfg, run)
        print('Repaired figures re-exported. Review them, then run approve.', flush=True)
        return
    targets = {(c['question'], c['filename']) for c in audit_run(run) if c['review_required']}
    for review in (run / 'review_required').glob('*.json'):
        record = json.loads(review.read_text(encoding='utf-8'))
        targets |= {(str(record['question']), f) for f in record.get('figures', {}) if f.endswith('.png')}
    out_dir = run / 'repair'
    out_dir.mkdir(exist_ok=True)
    listing = {}
    for number, filename in sorted(targets, key=lambda t: (int(t[0]) if t[0].isdigit() else 0, t[1])):
        try:
            evidence = frame(number, filename)
        except ValueError as exc:
            listing[f'{number}/{filename}'] = {'error': str(exc)}
            continue
        with Image.open(evidence['source_body']) as image:
            src = image.convert('RGB')
        box = evidence['source_pixel_box']
        cands = {'current': box, **options(src, box)}
        listing[f'{number}/{filename}'] = {k: {'box': v, 'edges': edge_diagnosis(src, v) or 'clean'} for k, v in cands.items()}
        cell, cols = 520, 3
        rows = (len(cands) + cols - 1) // cols
        sheet = Image.new('RGB', (cols * cell, rows * cell), 'white')
        draw = ImageDraw.Draw(sheet)
        for i, (name, b) in enumerate(cands.items()):
            tile = src.crop(b)
            tile.thumbnail((cell - 20, cell - 40))
            x, y = (i % cols) * cell, (i // cols) * cell
            sheet.paste(tile, (x + 5, y + 25))
            draw.rectangle((x + 5, y + 25, x + 5 + tile.width, y + 25 + tile.height), outline='blue')
            state = edge_diagnosis(src, b)
            draw.text((x + 5, y + 6), f'{name}: {"clean" if not state else ", ".join(state)}', fill='red')
        sheet.save(out_dir / f'{number}__{filename}')
    dump(out_dir / 'candidates.json', listing)
    print(f'{len(listing)} figure(s) to review; candidate sheets in {out_dir}', flush=True)
    for key, cands in listing.items():
        clean = [k for k, v in cands.items() if isinstance(v, dict) and v.get('edges') == 'clean' and k != 'current']
        print(f'  {key}: clean options {clean or "none"}', flush=True)


def _question_files(run, manifest, number):
    qdir = run / 'Outputs' / str(manifest['paper_id']) / str(number)
    files = [qdir / 'question.tex', qdir / 'solution.tex'] + sorted((qdir / 'figures').glob('[qs]fig*.png'))
    return {str(f.relative_to(qdir)).replace('\\', '/'): sha(f) for f in files if f.is_file()}


def approve(cfg, run, by, note, questions=None):
    """Record a HUMAN review decision; never called by extraction.

    Approves held/flagged items of the chosen questions (default: all with a
    review record or a flagged crop). Each approval is bound to the SHA-256 of
    the reviewed question.tex/solution.tex/figures: any later change to those
    files invalidates it and verify blocks again.
    """
    if not by or not note:
        raise ValueError('approve needs --by (reviewer) and --note (what was checked)')
    from crop_quality import audit_run
    manifest = json.loads((run / 'manifest.json').read_text(encoding='utf-8'))
    flagged = {c['question'] for c in audit_run(run) if c['review_required']}
    held = {f.stem for f in (run / 'review_required').glob('*.json')}
    chosen = sorted(set(questions) if questions else flagged | held, key=lambda n: (len(n), n))
    known = {item['number'] for item in manifest['items']}
    records = {}
    for number in chosen:
        if number not in known:
            raise ValueError(f'Question {number!r} is not in this run')
        hashes = _question_files(run, manifest, number)
        if not {'question.tex', 'solution.tex'} <= hashes.keys():
            raise ValueError(f'Question {number!r} has no complete transcription to approve')
        records[number] = hashes
    at = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    approvals_file = run / 'crop_approvals.json'
    approvals = json.loads(approvals_file.read_text(encoding='utf-8')) if approvals_file.exists() else {}
    for number, hashes in records.items():
        for name, digest in hashes.items():
            if name.startswith('figures/'):
                approvals[f'{number}/{name.split("/", 1)[1]}'] = digest
        review = run / 'review_required' / f'{number}.json'
        record = json.loads(review.read_text(encoding='utf-8')) if review.exists() else {'question': number}
        record.update({'approved': True, 'approval': {'by': by, 'at': at, 'note': note, 'hashes': hashes}})
        dump(review, record)
    dump(approvals_file, approvals)
    print(f'Approved {len(chosen)} question(s) by {by}: {chosen}', flush=True)


def verify(cfg, run):
    import database
    manifest = json.loads((run / 'manifest.json').read_text(encoding='utf-8'))
    progress = json.loads((run / 'progress.json').read_text(encoding='utf-8'))
    errors = []
    untagged = []
    approved_unreadable = set()
    for review in (run / 'review_required').glob('*.json'):
        record = json.loads(review.read_text(encoding='utf-8'))
        approval = record.get('approval') or {}
        if not record.get('approved'):
            errors.append(f'Unresolved extraction review: {review.name}: {record.get("reason", "")}')
        elif not approval.get('hashes') or approval['hashes'] != _question_files(run, manifest, record['question']):
            errors.append(f'{review.name}: files changed after approval by {approval.get("by")}; review again')
        elif record.get('unreadable'):
            approved_unreadable.add(str(record['question']))
    if cfg.get('raster_exact_crop', False):
        from crop_quality import audit_run, approval_errors
        crop_report = audit_run(run)
        approval_file = run / 'crop_approvals.json'
        approvals = json.loads(approval_file.read_text(encoding='utf-8')) if approval_file.exists() else {}
        current_hashes = {
            f'{crop["question"]}/{crop["filename"]}': sha(
                run / 'Outputs' / str(manifest['paper_id']) / str(crop['question']) / 'figures' / crop['filename']
            ) for crop in crop_report
        }
        errors.extend(approval_errors(crop_report, approvals, current_hashes))
    pid = manifest['paper_id']
    with database.get_connection() as c:
        if c.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': errors.append('DB integrity check failed')
        if c.execute('PRAGMA foreign_key_check').fetchall(): errors.append('Foreign key check failed')
        count = c.execute('SELECT count(*) FROM questions WHERE paper_id=?', (pid,)).fetchone()[0]
        if count != len(manifest['items']): errors.append('Question count mismatch')
        for qt, qn in c.execute('SELECT qtype, question_number FROM questions WHERE paper_id=?', (pid,)).fetchall():
            if qt not in database.QTYPE_VALUES:
                errors.append(f'{qn}: qtype {qt!r} outside {sorted(database.QTYPE_VALUES)}')
        for item in manifest['items']:
            if not progress['questions'].get(item['number'], {}).get('ok'):
                errors.append(f'{item["number"]}: extraction incomplete')
            errors.extend(f'{item["number"]}: {e}' for e in validate_item(pid, item['number'], bool(item['solution_rows']), item_has_key(item))
                          if not (item['number'] in approved_unreadable and 'unreadable content requires review' in e))
            node3 = progress['node3'].get(item['number'], {})
            if not node3.get('ok'):
                if cfg.get('allow_untagged') and is_abstention(node3):
                    untagged.append(item['number'])  # PaperLab's Tagging Inbox takes it
                else:
                    errors.append(f'{item["number"]}: Node 3 incomplete')
            for side in ('question', 'solution'):
                for row in item[f'{side}_rows']:
                    ev = row['asset_evidence']
                    if sha(ev['path']) != ev['sha256']: errors.append(f'Source asset changed: {row["id"]}')
        if c.execute('SELECT count(*) FROM token_usage WHERE input<0 OR output<0 OR cache_read<0 OR cache_read>input').fetchone()[0]:
            errors.append('Invalid token usage counters')
        for key in ('question_pdf', 'solution_pdf'):
            if manifest.get(key) and sha(manifest[key]) != manifest[key+'_sha256']: errors.append(f'{key} changed')
        usage = [dict(r) for r in c.execute('SELECT phase,count(*) calls,sum(input) input,sum(cache_read) cached,sum(output) output,sum(reasoning) reasoning FROM token_usage WHERE paper_id=? GROUP BY phase', (pid,))]
        topics = c.execute('SELECT count(*) FROM question_topics qt JOIN questions q ON q.id=qt.question_id WHERE q.paper_id=? AND qt.src=?', (pid, 'auto')).fetchone()[0]
    report = {'ok': not errors, 'paper_id': pid, 'questions': count, 'auto_topic_links': topics, 'untagged': untagged,
              'usage': usage,
              'errors': errors, 'upstream_commit': manifest['upstream_commit']}
    dump(run / 'verification.json', report)
    print(json.dumps(report, indent=2), flush=True)
    if errors: raise SystemExit(1)
    return report


def export_bundle(cfg, run, out=None):
    """Verify the run and package it as ONE portable PaperLab bundle (.plbundle).

    The file can be copied to any machine (Windows/macOS/Linux) and merged
    with ``python -m paperlab_bundle merge``. It carries the run DB rows,
    Outputs, source PDFs and, per paper, every review record together with
    its approval (who, when, what, file hashes). Refuses while verify() fails,
    so unapproved holds can never be exported.
    """
    import sys
    sys.path.insert(0, str(REPO))
    from paperlab_bundle import build_bundle
    verification = verify(cfg, run)  # only verified work is exportable
    manifest = json.loads((run / 'manifest.json').read_text(encoding='utf-8'))
    reviews = {}
    for record in sorted((run / 'review_required').glob('*.json')):
        rec = json.loads(record.read_text(encoding='utf-8'))
        reviews[record.stem] = rec
    approvals_file = run / 'crop_approvals.json'
    crop_approvals = json.loads(approvals_file.read_text(encoding='utf-8')) if approvals_file.exists() else {}
    name = manifest.get('paper_name') or f'paper-{manifest["paper_id"]}'
    safe = re.sub(r'[^\w\- .()]+', '_', name, flags=re.UNICODE).strip(' ._') or 'bundle'
    out = Path(out or run / f'{safe}.plbundle')
    producer = {
        'tool': 'importer_EJEE', 'stage': 'verify+export',
        'source': cfg.get('book_source'), 'part': manifest.get('part'),
        'upstream_commit': manifest.get('upstream_commit'),
    }
    return build_bundle(
        run / 'paperlab.db', out, [manifest['paper_id']], producer=producer,
        extra={manifest['paper_id']: {
            'paper_name': name,
            'reviews': reviews,                 # each with its human approval
            'crop_approvals': crop_approvals,   # "question/figure": approved PNG sha256
            'verification': verification,
            'source_refs': {item['number']: item.get('source_number', item['number'])
                            for item in manifest['items']},
        }},
        sources={manifest['paper_id']: [manifest[k] for k in ('question_pdf', 'solution_pdf') if manifest.get(k)]})


def plan_catalog(cfg, run):
    """Freeze per-book part plans for the WHOLE source database (no LLM)."""
    import book_plan
    out = run
    report = book_plan.catalog(cfg['source_db'], cfg['asset_root'], out, cfg.get('part_size', 15))
    planned = [r for r in report if r.get('status') == 'planned']
    print(f"Sources: {len(report)}; planned books: {len(planned)}; "
          f"excluded: {sum(r.get('status') == 'excluded' for r in report)}; "
          f"concept-only: {sum(r.get('status') == 'concept-only' for r in report)}", flush=True)
    print(f"Ready questions: {sum(r['ready'] for r in planned)}; blocked: {sum(r['blocked'] for r in planned)}; "
          f"parts: {sum(r['parts'] for r in planned)}. Catalog: {out / 'catalog.json'}", flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=['inspect', 'plan', 'prepare', 'extract', 'figures', 'classify', 'pack', 'verify', 'approve', 'repair', 'export', 'merge'])
    p.add_argument('--by', default=None, help='approve/repair: reviewer name')
    p.add_argument('--pick', action='append', default=None,
                   help='repair only: Q/figure=option[,option] e.g. 10/sfig1.png=bottom-out')
    p.add_argument('--note', default=None, help='approve only: what was checked')
    p.add_argument('--questions', default=None, help='approve only: comma-separated question numbers (default: all held/flagged)')
    p.add_argument('--out', default=None, help='export only: bundle file path (default: <run>/<paper name>.plbundle)')
    p.add_argument('--config', required=True, help='run config, e.g. written by run_book.py')
    p.add_argument('--target-db', default=None,
                   help='merge only: explicit archive database receiving the run')
    p.add_argument('--target-outputs', default=None,
                   help='merge only: Outputs base for the archive (default: <target-db-dir>/Outputs)')
    args = p.parse_args()
    cfg, run = load_config(args.config)
    activate(run)
    if args.phase == 'repair':
        picks = {}
        for spec in args.pick or []:
            key, _, steps = spec.partition('=')
            picks[key.strip()] = [x.strip() for x in steps.split(',') if x.strip()]
        return repair(cfg, run, picks or None, args.by)
    if args.phase == 'approve':
        return approve(cfg, run, args.by, args.note, args.questions.split(',') if args.questions else None)
    if args.phase == 'merge':
        if args.target_db:
            cfg['merge_target_db'] = args.target_db
        if args.target_outputs:
            cfg['merge_target_outputs'] = args.target_outputs
        merge(cfg, run)
    else:
        if args.phase == 'export':
            out = export_bundle(cfg, run, args.out)
            print(json.dumps({k: v for k, v in out.items() if k != 'files'}, indent=1, ensure_ascii=False), flush=True)
            return
        {'inspect': inspect_source, 'plan': plan_catalog, 'prepare': prepare, 'extract': extract,
         'figures': figures, 'classify': classify, 'pack': pack, 'verify': verify}[args.phase](cfg, run)


if __name__ == '__main__':
    main()
