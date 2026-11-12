"""EJEE chapter import: read-only source -> mapped image PDFs -> Node 2 -> Node 3.

Usage: python importer.py inspect|prepare|extract|classify|verify --config demo.json
   Step 1 (staging): prepare..verify write only the run's temp DB.
   Step 2 (merge):  python importer.py merge --config run.json --target-db /path/to/physics_archive.db
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
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
    cfg = json.loads(path.read_text(encoding='utf-8'))
    for key in ('source_db', 'asset_root', 'original_pdf'):
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


def prepare(cfg, run):
    import fitz
    import database
    if (run / 'manifest.json').exists():
        raise ValueError('Run already prepared; use extract/classify to resume, or choose a new run_dir')
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
                  (f'{cfg["book_source"]} — Chapter {cfg["chapter"]}: {cfg["chapter_title"]}', 'Textbook', cfg['book_source'], nq, 1 if ns else None, ns or None, 'uploaded', pid))
    commit = subprocess.check_output(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], text=True).strip()
    manifest = {'schema': 'ejee-paperlab-import/1', 'paper_id': pid, 'config': cfg,
                'upstream_commit': commit, 'question_pdf': str(qpath), 'solution_pdf': str(spath) if ns else None,
                'question_pdf_sha256': sha(qpath), 'solution_pdf_sha256': sha(spath) if ns else None,
                'items': items}
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


def normalize_rendering(tex, number=None):
    """Keep valid TeX while targeting the unchanged PaperLab/KaTeX bridge.

    With ``number`` (the fixed local question_number), the Answer label and
    every Solution-for heading are rewritten to it: the LLM sometimes echoes
    the printed source label (1.3) instead of the local ID (3), while the DB,
    folders and reader all key on the local ID. Only these two marker
    patterns are touched -- equation tags like (1.22) are never rewritten.
    """
    tex = re.sub(r'\\eqno\s*\(([^)\n]+)\)', lambda m: r'\tag{' + m[1] + '}', tex)
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
        tex = re.sub(r'(\\underline\{\\textbf\{Solution for )[^}]*(?=\}\})',
                     r'\g<1>' + str(number), tex)
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


def validate_item(pid, number, has_solution):
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
            for sm in re.finditer(r'\\underline\{\\textbf\{Solution for ([^}]*)\}\}', text):
                if prange is not None:
                    if not (sm.group(1).strip().isdigit()
                             and prange[0] <= int(sm.group(1).strip()) <= prange[1]):
                        errors.append(f'Solution-for sub-label {sm.group(1).strip()!r} outside {number}')
                elif sm.group(1).strip() != str(number):
                    errors.append(f'Solution-for {sm.group(1).strip()!r} != local question_number {number!r}')
        if re.search(r'\$\$[^\$]*?\\tag\{', text):
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
    by_name = {t.name: t for t in selected}
    native = (REPO / 'prompts' / 'extractor_prompt.md').read_text(encoding='utf-8')
    override = (ROOT / 'prompts' / 'mapped_extractor.md').read_text(encoding='utf-8')
    allowed = {manifest['question_pdf']: item['question_pages']}
    if manifest['solution_pdf']: allowed[manifest['solution_pdf']] = item['solution_pages']
    metadata = {'paper_id': pid, 'question_number': number, 'source_label': item['question_rows'][0]['title'],
                'source_groups': item.get('groups', [item['group']]),
                'allowed_pages': allowed, 'has_mapped_solution': bool(item['solution_rows']),
                'source_answers': [r['answer'] for r in item['question_rows'] if r['answer']],
                'source_question_text': [r['question'] for r in item['question_rows'] if r['question']],
                'source_solution_text': [r['solution'] for r in item['question_rows'] if r['solution']],
                'source_qtype': [r['qtype'] for r in item['question_rows'] if r['qtype']]}
    metadata['reviewed_diagrams'] = reuse_reviewed(cfg, item, pid, number)
    messages = [SystemMessage(content=native + '\n\n' + override), HumanMessage(content=json.dumps(metadata, ensure_ascii=False))]
    # Existing resource mapping supplies the images immediately; no searching/indexing calls.
    for side in ['question', 'solution']:
        for row, page in zip(item[f'{side}_rows'], item[f'{side}_pages']):
            messages.append(HumanMessage(content=[{'type': 'text', 'text': f'{side.upper()} page {page}, resource {row["id"]}; already body-cropped, no key-sheet assumption.'},
                                                    tools.img_block(row['asset_evidence']['body_png'], tools.PAGE_PX)]))
    llm = get_llm().bind_tools(selected, parallel_tool_calls=False)
    saved = set(); t0 = time.time()
    log = run / 'traces' / f'{number}.json'
    for turn in range(cfg.get('max_turns_per_question', 36)):
        response = invoke_with_retry(llm, messages)
        usage = response.usage_metadata or {}
        database.log_token_usage(pid, 'extractor', input_tokens=usage.get('input_tokens', 0),
                                 cache_read=(usage.get('input_token_details') or {}).get('cache_read', 0),
                                 output_tokens=usage.get('output_tokens', 0),
                                 reasoning_tokens=(usage.get('output_token_details') or {}).get('reasoning', 0))
        messages.append(response)
        for call in response.tool_calls or []:
            args = dict(call['args']); name = call['name']
            try:
                if name not in by_name: raise ValueError('Tool not allowed')
                if name == 'submit_question':
                    args['latex_content'] = strip_problem_heading(args['latex_content'], source_heading(item))
                if name == 'submit_solution':
                    args['latex_content'] = strip_solution_heading(args['latex_content'], source_heading(item))
                if name in ('submit_question', 'submit_solution'):
                    args['latex_content'] = normalize_rendering(args['latex_content'], number)
                if 'paper_id' in args and args['paper_id'] != pid: raise ValueError('Wrong paper ID')
                if 'question_number' in args and str(args['question_number']) != number: raise ValueError('Wrong question number')
                if 'pdf_path' in args:
                    if args['pdf_path'] not in allowed or args.get('page_number') not in allowed[args['pdf_path']]:
                        raise ValueError('PDF/page is outside this mapped question')
                if name in ('assisted_crop', 'exact_crop'):
                    prefix = 'qfig' if args['pdf_path'] == manifest['question_pdf'] else 'sfig'
                    if not re.fullmatch(prefix + r'\d+\.png', args.get('output_filename', '')):
                        raise ValueError('Use the correct side and stable qfigN.png/sfigN.png filename')
                if name in ('get_page_image', 'assisted_crop', 'exact_crop'):
                    result = by_name[name].invoke({'name': name, 'args': args, 'id': call['id'], 'type': 'tool_call'})
                else:
                    result = by_name[name].invoke(args)
                if isinstance(result, Command): messages.extend(result.update.get('messages', []))
                else:
                    messages.append(ToolMessage(content=str(result), tool_call_id=call['id']))
                    if name in ('submit_question', 'submit_solution') and str(result) == 'saved': saved.add(name)
            except Exception as exc:
                messages.append(ToolMessage(content=f'Error: {type(exc).__name__}: {exc}', tool_call_id=call['id']))
        dump(log, {'turns': turn+1, 'elapsed_sec': time.time()-t0, 'messages': [clean_message(m) for m in messages]})
        if len(saved) == 2:
            errors = validate_item(pid, number, bool(item['solution_rows']))
            if not errors: return {'ok': True, 'turns': turn+1, 'elapsed_sec': round(time.time()-t0, 2)}
            messages.append(HumanMessage(content='Completion check failed; correct with same IDs: ' + '; '.join(errors)))
        elif not response.tool_calls:
            messages.append(HumanMessage(content='Finish this mapped item by calling both submit_question and submit_solution. Do not invent missing solutions.'))
    raise RuntimeError(f'{number}: turn limit reached; trace saved for review')


def extract(cfg, run):
    import database
    manifest = json.loads((run / 'manifest.json').read_text(encoding='utf-8'))
    progress = json.loads((run / 'progress.json').read_text(encoding='utf-8'))
    pid = manifest['paper_id']; t0 = time.time()
    database.set_paper_status(pid, 'extracting')
    for item in manifest['items']:
        number = item['number']
        if progress['questions'].get(number, {}).get('ok') and not validate_item(pid, number, bool(item['solution_rows'])):
            continue
        print(f'Extracting {number} ({len(item["solution_rows"])} solution parts)', flush=True)
        try:
            progress['questions'][number] = extract_item(manifest, item, cfg, run)
        except Exception as exc:
            progress['questions'][number] = {'ok': False, 'error': f'{type(exc).__name__}: {exc}'}
            database.set_paper_status(pid, 'failed', progress['questions'][number]['error'], time.time()-t0)
            dump(run / 'progress.json', progress)
            raise
        dump(run / 'progress.json', progress)
        print(f'{number}: {progress["questions"][number]}', flush=True)
    elapsed = sum(r.get('elapsed_sec', 0) for r in progress['questions'].values())
    database.set_paper_status(pid, 'done', elapsed_sec=elapsed)
    database.mark_paper_archived(pid)
    print(f'Extraction complete: {len(manifest["items"])} questions. Run classify next.', flush=True)


def valid_classification(report):
    # Upstream explicitly permits no matching topic with a new-topic suggestion.
    return bool(report.get('difficulty') and (report.get('codes') or report.get('suggestion')) and not report.get('errors'))


def reviewed_crops(cfg):
    return json.loads((ROOT / cfg['reviewed_crops']).read_text(encoding='utf-8')) if cfg.get('reviewed_crops') else []


def node3_inputs_hash() -> dict:
    """Fingerprint everything upstream classification depends on.

    Seed rows, the topic prompt, and the upstream commit: any change here
    can shift topic numbering or the parse contract, so cached auto tags
    must not survive it (re-running stale tags would silently misfile
    questions). Best-effort commit (None outside git); the file hashes are
    the load-bearing part.
    """
    files = {
        'seed': REPO / 'topics_seed.json',
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


def reuse_reviewed(cfg, item, pid, number):
    """Reuse only reviewed isolated rectangles whose source pixel hash still matches."""
    from PIL import Image
    import directory_manager
    reused = []
    for crop in reviewed_crops(cfg):
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
    import database
    from run_topics import build_topic_list, classify_question
    manifest = json.loads((run / 'manifest.json').read_text(encoding='utf-8'))
    progress = json.loads((run / 'progress.json').read_text(encoding='utf-8'))
    lines = [f'Topic {n} — {p}' for n, p in build_topic_list()]
    meta = node3_inputs_hash()
    if progress.get('node3_meta') not in (None, meta):
        # Seed, prompt or upstream moved under a cached classification:
        # cached auto tags would misfile questions, so drop them and redo.
        # Explicit and loud (re-running costs API calls, keeping stale tags
        # costs correctness).
        print(f'Node 3 inputs changed (was {progress["node3_meta"]}); '
              f'discarding {len(progress.get("node3", {}))} cached classification(s).', flush=True)
        progress['node3'] = {}
    progress['node3_meta'] = meta
    for item in manifest['items']:
        number = item['number']
        if not progress['questions'].get(number, {}).get('ok'): raise ValueError('Extraction must finish first')
        previous = progress['node3'].get(number, {})
        if valid_classification(previous):
            previous['ok'] = True
            dump(run / 'progress.json', progress)
            continue
        report = classify_question(manifest['paper_id'], number, lines)
        report['ok'] = bool(report.get('ok') and valid_classification(report))
        progress['node3'][number] = report
        dump(run / 'progress.json', progress)
        print(f'Node 3 {number}: {report}', flush=True)
        if not report['ok']: raise RuntimeError('Node 3 output incomplete; retry classify after inspection')
        time.sleep(1)


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
                px = [max(0, math.floor((x-1)*im.width/1000)), max(0, math.floor((y-1)*im.height/1000)),
                      min(im.width, math.ceil((x+w+1)*im.width/1000)), min(im.height, math.ceil((y+h+1)*im.height/1000))]
                review = next((r for r in reviewed_crops(cfg) if r['group'] in item.get('groups', [item['group']]) and r['filename'] == filename and r['source_body_sha256'] == source['body_sha256']), None)
                if review: px = review['source_pixel_box']
                cropped = im.crop(px)
                dest = qdir / 'figures' / filename
                cropped.save(dest, format='PNG')
                evidence[filename] = {'source_body': source['body_png'], 'source_sha256': source['body_sha256'],
                                      'tool_final_box': box, 'source_pixel_box': px, 'size': list(cropped.size),
                                      'sha256': sha(dest), 'method': 'lossless source-pixel crop; one normalized unit safety margin'}
                if review: evidence[filename]['review_override'] = review
        for reused in reuse_reviewed(cfg, item, manifest['paper_id'], item['number']):
            crop = next(r for r in reviewed_crops(cfg) if r['group'] in item.get('groups', [item['group']]) and r['filename'] == reused['filename'])
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


def pack(cfg, run):
    """Normalize legacy pilot IDs and renderer-sensitive heading stars in DATA only."""
    import database
    import directory_manager
    manifest = json.loads((run / 'manifest.json').read_text(encoding='utf-8'))
    progress = json.loads((run / 'progress.json').read_text(encoding='utf-8'))
    changes = []
    pattern = re.compile(cfg['group_pattern'])
    for item in manifest['items']:
        old = item['number']
        if len(item.get('groups', [item['group']])) > 1:
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
                verdict = verify_latex_syntax(after)
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
    """
    import database
    verify(cfg, run)  # fail first, merge never
    manifest = json.loads((run / 'manifest.json').read_text(encoding='utf-8'))
    rundb = (run / 'paperlab.db').resolve()
    target = Path(target_db or cfg.get('merge_target_db') or (REPO / 'physics_archive.db')).resolve()
    outbase = Path(target_outputs or cfg.get('merge_target_outputs') or (target.parent / 'Outputs')).resolve()
    if target == rundb:
        raise ValueError('Merge target is the run database itself; point --target-db at the archive.')
    if ROOT in target.parents:
        raise ValueError('Merge target is inside importer_EJEE (a temp run DB); point --target-db at the archive.')
    already = manifest.get('merged') or {}
    if already.get('target_db') == str(target):
        raise ValueError(f'Already merged into {target} as paper {already["paper_id"]} '
                         f'at {already["at"]} (backup {already["backup"]}).')
    with database.get_connection(str(rundb)) as rc:
        paper = rc.execute('SELECT * FROM papers WHERE id=?', (manifest['paper_id'],)).fetchone()
        if paper is None:
            raise ValueError(f'Run paper {manifest["paper_id"]} missing from {rundb}')
        paper = dict(paper)
        questions = [dict(r) for r in rc.execute(
            'SELECT * FROM questions WHERE paper_id=? ORDER BY question_number', (manifest['paper_id'],))]
        qids = [q['id'] for q in questions]
        links, usage = [], []
        if qids:
            ph = ','.join('?' for _ in qids)
            links = [dict(r) for r in rc.execute(
                f'SELECT question_id, topic_code, rank, src FROM question_topics WHERE question_id IN ({ph})', qids)]
        usage = [dict(r) for r in rc.execute(
            'SELECT phase, input, cache_read, output, reasoning, ts FROM token_usage WHERE paper_id=?',
            (manifest['paper_id'],))]
    existed = target.is_file()
    if existed:
        stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
        backup = target.parent / f'{target.stem}.pre-merge-{stamp}.bak'
        with sqlite3.connect(str(target)) as src, sqlite3.connect(str(backup)) as dst:
            src.backup(dst)
    else:
        backup = None
    database.init_db(str(target))
    database.init_topics(str(target))
    with database.get_connection(str(target)) as tc:
        if tc.execute('SELECT id FROM papers WHERE pdf_hash=?', (paper['pdf_hash'],)).fetchone() is not None:
            dup = tc.execute('SELECT id FROM papers WHERE pdf_hash=?', (paper['pdf_hash'],)).fetchone()['id']
            raise ValueError(f'Target already holds this PDF pair as paper {dup}; merge refused as duplicate.')
        cols = [r['name'] for r in tc.execute('PRAGMA table_info(papers)').fetchall() if r['name'] != 'id']
        tc.execute(f'INSERT INTO papers ({",".join(cols)}) VALUES ({",".join("?" for _ in cols)})',
                   [paper.get(c) for c in cols])
        new_pid = tc.execute('SELECT last_insert_rowid()').fetchone()[0]
        qcols = [r['name'] for r in tc.execute('PRAGMA table_info(questions)').fetchall() if r['name'] != 'id']
        idmap, moved = {}, []
        for q in questions:
            new_folder = outbase / str(new_pid) / q['question_number']
            old_folder = Path(q['latex_folder'])
            if not old_folder.is_dir():
                raise ValueError(f'Run question folder missing: {old_folder}')
            new_folder.parent.mkdir(parents=True, exist_ok=True)
            if new_folder.exists():
                raise ValueError(f'Target folder already exists: {new_folder}')
            shutil.copytree(old_folder, new_folder)
            moved.append(str(new_folder))
            row = {c: q.get(c) for c in qcols}
            row['paper_id'] = new_pid
            row['latex_folder'] = str(new_folder)
            tc.execute(f'INSERT INTO questions ({",".join(qcols)}) VALUES ({",".join("?" for _ in qcols)})',
                       [row[c] for c in qcols])
            idmap[q['id']] = tc.execute('SELECT last_insert_rowid()').fetchone()[0]
        for link in links:
            tc.execute('INSERT INTO question_topics (question_id, topic_code, rank, src) VALUES (?,?,?,?)',
                       (idmap[link['question_id']], link['topic_code'], link['rank'], link['src']))
        for u in usage:
            tc.execute('INSERT INTO token_usage (paper_id, phase, input, cache_read, output, reasoning, ts)'
                       ' VALUES (?,?,?,?,?,?,?)',
                       (new_pid, u['phase'], u['input'], u['cache_read'], u['output'], u['reasoning'], u['ts']))
        srcdir = outbase / str(new_pid) / '_source'
        srcdir.mkdir(parents=True, exist_ok=True)
        pdf_paths = {}
        for key in ('question_pdf', 'solution_pdf'):
            src = manifest.get(key)
            if not src:
                pdf_paths[key] = None
                continue
            dest = srcdir / Path(src).name
            shutil.copy2(src, dest)
            pdf_paths[key] = str(dest)
        tc.execute('UPDATE papers SET question_pdf_path=?, solution_pdf_path=? WHERE id=?',
                   (pdf_paths['question_pdf'], pdf_paths['solution_pdf'], new_pid))
        if tc.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Target integrity check failed after merge; transaction rolled back.')
        if tc.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Target foreign key check failed after merge; transaction rolled back.')
        got_q = tc.execute('SELECT count(*) FROM questions WHERE paper_id=?', (new_pid,)).fetchone()[0]
        if got_q != len(questions):
            raise ValueError(f'Merged {got_q} questions, expected {len(questions)}; rolled back.')
        got_l = tc.execute('SELECT count(*) FROM question_topics WHERE question_id IN '
                           '(SELECT id FROM questions WHERE paper_id=?)', (new_pid,)).fetchone()[0]
        if got_l != len(links):
            raise ValueError(f'Merged {got_l} topic links, expected {len(links)}; rolled back.')
    receipt = {'target_db': str(target), 'target_outputs': str(outbase), 'run': str(run),
               'paper_id': new_pid, 'questions': len(questions), 'topic_links': len(links),
               'usage_rows': len(usage), 'folders': moved,
               'question_pdf': pdf_paths['question_pdf'], 'solution_pdf': pdf_paths['solution_pdf'],
               'backup': str(backup) if backup else None, 'fresh_target': not existed,
               'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    dump(run / 'merge.json', receipt)
    manifest['merged'] = {'target_db': str(target), 'paper_id': new_pid,
                          'backup': receipt['backup'], 'at': receipt['at']}
    dump(run / 'manifest.json', manifest)
    print(f'Merged paper {manifest["paper_id"]} -> {target} as paper {new_pid}: '
          f'{len(questions)} questions, {len(links)} topic links, {len(usage)} usage rows. '
          + (f'Backup: {backup}.' if backup else 'Fresh target, no backup needed.'), flush=True)
    return receipt


def verify(cfg, run):
    import database
    manifest = json.loads((run / 'manifest.json').read_text(encoding='utf-8'))
    progress = json.loads((run / 'progress.json').read_text(encoding='utf-8'))
    errors = []
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
            errors.extend(f'{item["number"]}: {e}' for e in validate_item(pid, item['number'], bool(item['solution_rows'])))
            if not progress['node3'].get(item['number'], {}).get('ok'): errors.append(f'{item["number"]}: Node 3 incomplete')
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
    report = {'ok': not errors, 'paper_id': pid, 'questions': count, 'auto_topic_links': topics, 'usage': usage,
              'errors': errors, 'upstream_commit': manifest['upstream_commit']}
    dump(run / 'verification.json', report)
    print(json.dumps(report, indent=2), flush=True)
    if errors: raise SystemExit(1)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=['inspect', 'prepare', 'extract', 'figures', 'classify', 'pack', 'verify', 'merge'])
    p.add_argument('--config', default=str(ROOT / 'demo.json'))
    p.add_argument('--target-db', default=None,
                   help='merge only: archive database receiving the run (default: REPO/physics_archive.db)')
    p.add_argument('--target-outputs', default=None,
                   help='merge only: Outputs base for the archive (default: <target-db-dir>/Outputs)')
    args = p.parse_args()
    cfg, run = load_config(args.config)
    activate(run)
    if args.phase == 'merge':
        if args.target_db:
            cfg['merge_target_db'] = args.target_db
        if args.target_outputs:
            cfg['merge_target_outputs'] = args.target_outputs
        merge(cfg, run)
    else:
        {'inspect': inspect_source, 'prepare': prepare, 'extract': extract,
         'figures': figures, 'classify': classify, 'pack': pack, 'verify': verify}[args.phase](cfg, run)


if __name__ == '__main__':
    main()
