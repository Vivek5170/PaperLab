"""EJEE chapter import: read-only source -> mapped image PDFs -> Node 2 -> Node 3.

Usage: python importer.py inspect|prepare|extract|classify|verify --config demo.json
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
    run = (ROOT / cfg['run_dir']).resolve()
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


def prepare(cfg, run):
    import fitz
    import database
    if (run / 'manifest.json').exists():
        raise ValueError('Run already prepared; use extract/classify to resume, or choose a new run_dir')
    pattern = re.compile(cfg['group_pattern'])
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
        items = []
        for grp, rows in sorted(groups.items(), key=lambda pair: int(pattern.fullmatch(pair[0])['number'])):
            if any(r['part'] not in ('q', 'sol') for r in rows):
                raise ValueError(f'Unsupported part in {grp}; explicit adapter required')
            qrows = sorted([r for r in rows if r['part'] == 'q'], key=part_order)
            srows = sorted([r for r in rows if r['part'] == 'sol'], key=part_order)
            if not qrows:
                raise ValueError(f'Orphan solution group {grp}')
            if len(qrows) > 1 and not all(re.search(r'\(\d+/\d+\)', r['title']) for r in qrows):
                raise ValueError(f'Ambiguous multiple question rows in {grp}')
            rid = [r['id'] for r in rows]
            placeholders = ','.join('?' for _ in rid)
            crops = [dict(r) for r in c.execute(f'SELECT * FROM resource_crops WHERE resource_id IN ({placeholders})', rid)]
            transcripts = [dict(r) for r in c.execute(f'SELECT * FROM resource_transcripts WHERE resource_id IN ({placeholders})', rid)]
            ancestry = {}
            for r in rows:
                lineage, n, seen = [], r['topic_id'], set()
                while n in nodes and n not in seen:
                    seen.add(n); lineage.append(nodes[n]); n = nodes[n]['parent_id']
                ancestry[str(r['id'])] = lineage
            items.append({'group': grp, 'number': str(int(pattern.fullmatch(grp)['number'])),
                          'source_number': f'{cfg["chapter"]}.{pattern.fullmatch(grp)["number"]}',
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


def normalize_rendering(tex):
    """Keep valid TeX while targeting the unchanged PaperLab/KaTeX bridge."""
    tex = re.sub(r'\\eqno\s*\(([^)\n]+)\)', lambda m: r'\tag{' + m[1] + '}', tex)
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
        if side == 'solution' and has_solution and ('No solution provided.' in text or len(text.strip()) < 50):
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
                if name in ('submit_question', 'submit_solution'):
                    args['latex_content'] = normalize_rendering(args['latex_content'])
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


def reuse_reviewed(cfg, item, pid, number):
    """Reuse only reviewed isolated rectangles whose source pixel hash still matches."""
    from PIL import Image
    import directory_manager
    reused = []
    for crop in reviewed_crops(cfg):
        if crop['group'] != item['group']: continue
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
                review = next((r for r in reviewed_crops(cfg) if r['group'] == item['group'] and r['filename'] == filename and r['source_body_sha256'] == source['body_sha256']), None)
                if review: px = review['source_pixel_box']
                cropped = im.crop(px)
                dest = qdir / 'figures' / filename
                cropped.save(dest, format='PNG')
                evidence[filename] = {'source_body': source['body_png'], 'source_sha256': source['body_sha256'],
                                      'tool_final_box': box, 'source_pixel_box': px, 'size': list(cropped.size),
                                      'sha256': sha(dest), 'method': 'lossless source-pixel crop; one normalized unit safety margin'}
                if review: evidence[filename]['review_override'] = review
        for reused in reuse_reviewed(cfg, item, manifest['paper_id'], item['number']):
            crop = next(r for r in reviewed_crops(cfg) if r['group'] == item['group'] and r['filename'] == reused['filename'])
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
        old = item['number']; new = str(int(pattern.fullmatch(item['group'])['number']))
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
            after = normalize_rendering(strip_problem_heading(before, source_heading(item)) if side == 'question' else before)
            if after != before:
                path.write_text(after, encoding='utf-8')
                changes.append({'kind': 'content_and_rendering_normalization', 'question': new, 'side': side,
                                'before_sha256': hashlib.sha256(before.encode()).hexdigest(), 'after_sha256': sha(path),
                                'reason': 'Keep statement-only questions; normalize equation tags and preserve literal code rows for the unchanged native renderer.'})
    dump(run / 'manifest.json', manifest)
    dump(run / 'progress.json', progress)
    previous = json.loads((run / 'data_normalizations.json').read_text(encoding='utf-8')) if (run / 'data_normalizations.json').exists() else []
    dump(run / 'data_normalizations.json', previous + changes)
    print(f'Packed chapter with {len(changes)} recorded data normalizations; no application source edits.', flush=True)


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
    p.add_argument('phase', choices=['inspect', 'prepare', 'extract', 'figures', 'classify', 'pack', 'verify'])
    p.add_argument('--config', default=str(ROOT / 'demo.json'))
    args = p.parse_args()
    cfg, run = load_config(args.config)
    activate(run)
    {'inspect': inspect_source, 'prepare': prepare, 'extract': extract, 'figures': figures, 'classify': classify, 'pack': pack, 'verify': verify}[args.phase](cfg, run)


if __name__ == '__main__':
    main()
