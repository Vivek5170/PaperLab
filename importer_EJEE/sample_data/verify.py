"""Read-only fixture checks; standard library only, no API credentials needed."""
from pathlib import Path
import json
import re
import sqlite3

root = Path(__file__).resolve().parent
counts = {}
with sqlite3.connect((root/'paperlab.db').resolve().as_uri()+'?mode=ro',uri=True) as c:
    assert c.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert not c.execute('PRAGMA foreign_key_check').fetchall()
    for table in ('papers','questions','question_topics','token_usage'):
        counts[table] = c.execute('SELECT count(*) FROM '+table).fetchone()[0]
    assert counts['papers']==3 and counts['questions']==22
    for folder, in c.execute('SELECT latex_folder FROM questions'):
        assert not Path(folder).is_absolute()
        for side in ('question','solution'):
            text=(root/folder/f'{side}.tex').read_text(encoding='utf-8'); assert text.strip()
            for name in re.findall(r'\\includegraphics(?:\[[^\]]*\])?\{figures/([^}]+)\}',text):
                assert (root/folder/'figures'/name).is_file()
    for qp,sp in c.execute('SELECT question_pdf_path,solution_pdf_path FROM papers'):
        for value in (qp,sp):
            if value: assert not Path(value).is_absolute() and (root/value).is_file()
with sqlite3.connect((root/'ejee_sample.db').resolve().as_uri()+'?mode=ro',uri=True) as c:
    assert not c.execute('PRAGMA foreign_key_check').fetchall()
    assert not c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'ex_%'").fetchall()
    for name, in c.execute('SELECT file_name FROM resources'): assert (root/'source_assets'/name).is_file()
print(json.dumps({'ok':True,**counts},indent=2))
