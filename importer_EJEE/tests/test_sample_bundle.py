import json
from pathlib import Path
import re
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / 'sample_data'


def test_sample_bundle_is_portable_and_complete():
    with sqlite3.connect(f'file:{(SAMPLE / "paperlab.db").as_posix()}?mode=ro', uri=True) as c:
        assert c.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not c.execute('PRAGMA foreign_key_check').fetchall()
        assert c.execute('SELECT count(*) FROM papers').fetchone()[0] == 3
        assert c.execute('SELECT count(DISTINCT source_institute) FROM papers').fetchone()[0] == 2
        assert c.execute('SELECT count(*) FROM questions').fetchone()[0] == 22
        assert c.execute('SELECT count(*) FROM questions WHERE difficulty IS NOT NULL').fetchone()[0] == 22
        assert dict(c.execute('SELECT phase,count(*) FROM token_usage GROUP BY phase')) == {'extractor':72,'topics':22}
        figures = 0
        for folder, in c.execute('SELECT latex_folder FROM questions'):
            assert not Path(folder).is_absolute()
            for side in ('question','solution'):
                tex = (SAMPLE/folder/f'{side}.tex').read_text(encoding='utf-8')
                assert tex.strip()
                for name in re.findall(r'\\includegraphics(?:\[[^\]]*\])?\{figures/([^}]+)\}',tex):
                    assert (SAMPLE/folder/'figures'/name).is_file()
                    assert name.startswith('qfig' if side == 'question' else 'sfig')
                    figures += 1
        assert figures == 7
        for qp,sp in c.execute('SELECT question_pdf_path,solution_pdf_path FROM papers'):
            for path in (qp,sp):
                if path:
                    assert not Path(path).is_absolute()
                    assert (SAMPLE/path).is_file()


def test_source_fixture_has_no_student_or_exam_tables():
    with sqlite3.connect(f'file:{(SAMPLE / "ejee_sample.db").as_posix()}?mode=ro', uri=True) as c:
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert names == {'sqlite_sequence','nodes','resources','source_documents','resource_crops','resource_transcripts'}
        assert c.execute('SELECT count(*) FROM resources').fetchone()[0] == 40
        assert not c.execute('PRAGMA foreign_key_check').fetchall()
        for name, in c.execute('SELECT file_name FROM resources'):
            assert (SAMPLE/'source_assets'/name).is_file()


def test_all_sample_configs_resolve_to_minimal_input():
    import sys
    sys.path.insert(0,str(ROOT))
    from importer import load_config
    for path in (SAMPLE/'configs').glob('*.json'):
        cfg, run = load_config(path)
        assert Path(cfg['source_db']) == SAMPLE/'ejee_sample.db'
        assert Path(cfg['asset_root']) == SAMPLE/'source_assets'
        assert ROOT in run.parents
