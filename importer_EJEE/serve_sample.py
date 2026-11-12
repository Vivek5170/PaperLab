"""Launch the bundled sample in a separate writable review directory; no API key needed."""
import argparse
import hashlib
import shutil
import sqlite3
from pathlib import Path
from bootstrap import ROOT, activate

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--port', type=int, default=8001)
parser.add_argument('--fresh', action='store_true',
                    help='Discard the review copy (and any edits in it) and rebuild from the bundle.')
args = parser.parse_args()
sample = ROOT / 'sample_data'
run = ROOT / 'runs' / 'sample-review'


def _sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


stamp = run / '.bundle_stamp'
fingerprint = _sha(sample / 'paperlab.db')
stale = (
    args.fresh
    or not (run / 'paperlab.db').exists()
    or not (run / 'Outputs').is_dir()
    or not stamp.is_file()
    or stamp.read_text(encoding='utf-8').strip() != fingerprint
)
if stale:
    if run.exists():
        print(f'Rebuilding review copy from bundle (previous review edits are discarded).', flush=True)
        shutil.rmtree(run)
    run.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(sample / 'paperlab.db') as src, sqlite3.connect(run / 'paperlab.db') as dest:
        src.backup(dest)
    shutil.copytree(sample / 'Outputs', run / 'Outputs')
    # data/ (EJEE source PDFs/body images) is author-local and not in git;
    # copy it when present so paper-PDF links keep working, skip otherwise.
    if (sample / 'data').is_dir():
        shutil.copytree(sample / 'data', run / 'data')
    with sqlite3.connect(run / 'paperlab.db') as c:
        if c.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise SystemExit('Copied review database failed integrity_check')
        if c.execute('PRAGMA foreign_key_check').fetchall():
            raise SystemExit('Copied review database failed foreign_key_check')
        for pid, qn in c.execute('SELECT paper_id,question_number FROM questions').fetchall():
            folder = [r for r in c.execute(
                'SELECT latex_folder FROM questions WHERE paper_id=? AND question_number=?',
                (pid, qn))][0][0]
            if Path(folder).is_absolute():
                raise SystemExit(f'Bundle is not portable: absolute latex_folder {folder!r}')
            c.execute('UPDATE questions SET latex_folder=? WHERE paper_id=? AND question_number=?', (str(run / 'Outputs' / str(pid) / qn), pid, qn))
        for pid, qp, sp in c.execute('SELECT id,question_pdf_path,solution_pdf_path FROM papers').fetchall():
            for label, p in (('question_pdf', qp), ('solution_pdf', sp)):
                if p and Path(p).is_absolute():
                    raise SystemExit(f'Bundle is not portable: absolute {label} {p!r}')
            c.execute('UPDATE papers SET question_pdf_path=?,solution_pdf_path=? WHERE id=?', (str(run / qp) if qp else None, str(run / sp) if sp else None, pid))
    stamp.write_text(fingerprint, encoding='utf-8')
activate(run)
import uvicorn
print(f'Sample API: http://127.0.0.1:{args.port}; database: {run / "paperlab.db"}', flush=True)
uvicorn.run('backend.main:app', host='127.0.0.1', port=args.port)
