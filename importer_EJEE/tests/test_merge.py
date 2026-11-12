"""Merge-phase tests: a verified temp run promotes into an archive DB correctly."""
import hashlib
import importlib
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent))

os.environ.setdefault('PHYSICS_ARCHIVE_DB', str(Path(__file__).parent / 'tmp-never-created' / 'x.db'))

from importer import merge  # noqa: E402
import database  # noqa: E402


def _question_tex():
    return ('Which one is it?\n\n\\begin{enumerate}\n\\item one\n\\item two\n\\end{enumerate}\n')


def _solution_tex(number):
    return (f'\\textbf{{Answer: {number})}}\n\n'
            f'\\underline{{\\textbf{{Solution for {number}}}}}\n\n'
            'A worked explanation long enough to pass the placeholder guard.\n')


@pytest.fixture()
def staged_run(tmp_path, monkeypatch):
    """A minimal verified run: temp DB + Outputs + manifest, like prepare made."""
    rundir = tmp_path / 'run'
    monkeypatch.setenv('PHYSICS_ARCHIVE_DB', str(rundir / 'paperlab.db'))
    monkeypatch.setenv('PHYSICS_OUTPUT_BASE', str(rundir / 'Outputs'))
    importlib.reload(database)  # rebind DB_PATH to this run's temp DB
    database.init_db(str(rundir / 'paperlab.db'))
    database.init_topics(str(rundir / 'paperlab.db'))
    code = database.get_connection(str(rundir / 'paperlab.db')).execute(
        "SELECT code FROM topics WHERE level='subtopic' LIMIT 1").fetchone()['code']
    with database.get_connection(str(rundir / 'paperlab.db')) as c:
        pid = c.execute(
            "INSERT INTO papers (paper_name, exam_type, source_institute, pdf_hash, status, archive)"
            " VALUES ('M ch1','Textbook','Morin','hash-1','done',1)").lastrowid
        for number in ('1', '2'):
            latex = rundir / 'Outputs' / str(pid) / number
            (latex / 'figures').mkdir(parents=True)
            (latex / 'question.tex').write_text(_question_tex(), encoding='utf-8')
            (latex / 'solution.tex').write_text(_solution_tex(number), encoding='utf-8')
            qid = c.execute(
                "INSERT INTO questions (paper_id, question_number, latex_folder, status, qtype, difficulty)"
                " VALUES (?,?,?,?,?,?)",
                (pid, number, str(latex), 'done', 'scq', 'Medium')).lastrowid
            c.execute("INSERT INTO question_topics (question_id, topic_code, rank, src)"
                      " VALUES (?,?,?,?)", (qid, code, 0, 'auto'))
        c.execute("INSERT INTO token_usage (paper_id, phase, input, cache_read, output, reasoning)"
                  " VALUES (?,?,?,?,?,?)", (pid, 'extractor', 10, 2, 3, 0))
        c.commit()
    qpdf = rundir / 'sources' / 'questions.pdf'
    qpdf.parent.mkdir(parents=True, exist_ok=True)
    qpdf.write_bytes(b'%PDF-1.4 fake')
    asset = rundir / 'sources' / 'asset.png'
    asset.write_bytes(b'\x89PNG fake')
    evidence = {'path': str(asset), 'sha256': hashlib.sha256(asset.read_bytes()).hexdigest()}
    manifest = {'schema': 'ejee-paperlab-import/1', 'paper_id': pid,
                'config': {}, 'upstream_commit': 'test',
                'question_pdf': str(qpdf), 'solution_pdf': None,
                'question_pdf_sha256': hashlib.sha256(qpdf.read_bytes()).hexdigest(),
                'solution_pdf_sha256': None,
                'items': [{'number': n, 'solution_rows': [{'asset_evidence': evidence}],
                           'question_rows': [], 'question_pages': [], 'solution_pages': []}
                          for n in ('1', '2')]}
    (rundir / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    (rundir / 'progress.json').write_text(json.dumps(
        {'questions': {'1': {'ok': True}, '2': {'ok': True}},
         'node3': {'1': {'ok': True}, '2': {'ok': True}}}), encoding='utf-8')
    return rundir, {'merge_target_db': str(tmp_path / 'archive' / 'physics_archive.db')}


def test_merge_copies_everything_with_new_ids(staged_run):
    rundir, cfg = staged_run
    receipt = merge(cfg, rundir)
    target = Path(cfg['merge_target_db'])
    assert (receipt['paper_id'], receipt['questions']) == (1, 2)
    assert (receipt['topic_links'], receipt['usage_rows']) == (2, 1)
    assert receipt['backup'] is None  # fresh target: nothing to back up
    with database.get_connection(str(target)) as c:
        papers = c.execute('SELECT * FROM papers').fetchall()
        assert len(papers) == 1 and papers[0]['paper_name'] == 'M ch1'
        qs = c.execute('SELECT * FROM questions ORDER BY question_number').fetchall()
        assert [q['question_number'] for q in qs] == ['1', '2']
        assert all(q['paper_id'] == 1 for q in qs)
        assert all(Path(q['latex_folder']).is_dir() for q in qs)
        assert all(str(target.parent / 'Outputs') in q['latex_folder'] for q in qs)
        assert c.execute('SELECT count(*) FROM question_topics').fetchone()[0] == 2
        assert c.execute('SELECT count(*) FROM token_usage').fetchone()[0] == 1
        assert c.execute('PRAGMA foreign_key_check').fetchall() == []
    assert (target.parent / 'Outputs' / '1' / '1' / 'solution.tex').read_text(
        encoding='utf-8').startswith('\\textbf{Answer: 1)}')
    # Source PDF travelled with the paper, not left pointing at the temp run.
    assert Path(papers[0]['question_pdf_path']).is_file()
    assert str(rundir) not in papers[0]['question_pdf_path']
    saved = json.loads((rundir / 'manifest.json').read_text(encoding='utf-8'))
    assert saved['merged']['paper_id'] == 1
    assert (rundir / 'merge.json').is_file()


def test_merge_refuses_second_run_into_same_target(staged_run, tmp_path):
    rundir, cfg = staged_run
    merge(cfg, rundir)
    with pytest.raises(ValueError, match='Already merged'):
        merge(cfg, rundir)
    # The same run may still merge into a DIFFERENT archive.
    other = tmp_path / 'archive2' / 'other.db'
    receipt = merge(dict(cfg, merge_target_db=str(other)), rundir)
    assert receipt['paper_id'] == 1


def test_merge_refuses_duplicate_pdf_hash(staged_run):
    rundir, cfg = staged_run
    merge(cfg, rundir)
    twin = rundir.parent / 'run2'
    shutil.copytree(rundir, twin, ignore=shutil.ignore_patterns('merge.json'))
    manifest = json.loads((twin / 'manifest.json').read_text(encoding='utf-8'))
    manifest.pop('merged', None)
    (twin / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError, match='already holds this PDF pair'):
        merge(dict(cfg), twin)


def test_merge_requires_fresh_verify(staged_run):
    rundir, cfg = staged_run
    (rundir / 'Outputs' / '1' / '1' / 'solution.tex').write_text('garbage', encoding='utf-8')
    with pytest.raises(SystemExit):
        merge(cfg, rundir)
    assert not (rundir / 'merge.json').exists()
