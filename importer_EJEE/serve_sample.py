"""Launch the bundled sample in a separate writable review directory; no API key needed."""
import argparse
import json
import shutil
import sqlite3
from bootstrap import ROOT, activate

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--port', type=int, default=8001)
args = parser.parse_args()
sample = ROOT / 'sample_data'
run = ROOT / 'runs' / 'sample-review'
run.mkdir(parents=True, exist_ok=True)
if not (run / 'paperlab.db').exists():
    with sqlite3.connect(sample / 'paperlab.db') as src, sqlite3.connect(run / 'paperlab.db') as dest:
        src.backup(dest)
    for folder in ('Outputs', 'data'):
        shutil.copytree(sample / folder, run / folder, dirs_exist_ok=True)
    with sqlite3.connect(run / 'paperlab.db') as c:
        for pid,qn in c.execute('SELECT paper_id,question_number FROM questions').fetchall():
            c.execute('UPDATE questions SET latex_folder=? WHERE paper_id=? AND question_number=?', (str(run / 'Outputs' / str(pid) / qn), pid, qn))
        for pid,qp,sp in c.execute('SELECT id,question_pdf_path,solution_pdf_path FROM papers').fetchall():
            c.execute('UPDATE papers SET question_pdf_path=?,solution_pdf_path=? WHERE id=?', (str(run / qp) if qp else None, str(run / sp) if sp else None, pid))
activate(run)
import uvicorn
print(f'Sample API: http://127.0.0.1:{args.port}; database: {run / "paperlab.db"}', flush=True)
uvicorn.run('backend.main:app', host='127.0.0.1', port=args.port)
