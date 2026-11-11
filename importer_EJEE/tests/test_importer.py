import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from importer import body_image, part_order, source_connect, validate_item, load_config, valid_classification, strip_problem_heading, normalize_rendering


def test_equation_tags_and_literal_program_rows_survive_native_rendering():
    from bootstrap import REPO
    sys.path.insert(0,str(REPO))
    from backend.segments import rich_text
    from app.render import tex_to_markdown
    from urllib.parse import unquote
    import re
    original = '$$x=1. '+r'\eqno(1.21)'+'$$\n'+r'\begin{verbatim}'+'\n'+ 'r:=r+e*r1: # first row\nr2:=q1^2: # second row\ni*e;\n'+r'\end{verbatim}'
    fixed = normalize_rendering(original)
    assert normalize_rendering(fixed) == fixed
    assert r'\eqno' not in fixed and r'\tag{1.21}' in fixed
    assert r'\begin{verbatim}' not in fixed
    html = rich_text(tex_to_markdown(fixed))
    maths = [unquote(v) for v in re.findall(r'data-tex="([^"]+)"',html)]
    assert len(maths)==2
    assert r'\tag{1.21}' in maths[0]
    assert r'\begin{array}{ll}' in maths[1]
    assert maths[1].count(r'\\')==2
    assert r'\texttt{r:=r+e*r1:}' in maths[1]
    assert r'\texttt{\# first row}' in maths[1]
    assert r'q1\textasciicircum{}2' in maths[1]
    assert '<em>' not in html


def test_strip_verified_heading_preserves_inline_statement():
    assert strip_problem_heading(r'1.18. \textbf{Distance with damping} $\ast\ast$'+'\n\nA mass is subject to damping.', 'Distance with damping') == 'A mass is subject to damping.'
    assert strip_problem_heading(r'1.17. Pendulum ** A pendulum of length $\ell$ is released.', 'Pendulum') == r'A pendulum of length $\ell$ is released.'
    assert strip_problem_heading(r"1.13. \textbf{Atwood's machine $\star$} Consider three masses.", "Atwood's machine") == 'Consider three masses.'
    assert strip_problem_heading('1. A particle moves.', 'Damping') == '1. A particle moves.'


def test_live_source_is_read_only(tmp_path):
    db = tmp_path / 'source.db'
    with sqlite3.connect(db) as c:
        c.execute('CREATE TABLE resources(id INTEGER)')
        c.execute('INSERT INTO resources VALUES (9)')
    with source_connect(db) as c:
        assert c.execute('SELECT id FROM resources').fetchone()[0] == 9
        with pytest.raises(sqlite3.OperationalError):
            c.execute('DELETE FROM resources')


def test_body_box_is_lossless_and_not_a_diagram_guess(tmp_path):
    im = Image.new('RGB', (100, 200), 'white')
    im.putpixel((20, 40), (11, 22, 33))
    im.save(tmp_path / 'card.png')
    row = {'id': 1, 'file_name': 'card.png', 'print_meta': json.dumps({'box': [0.1, 0.1, 0.9, 0.9], 'keys': [[0, 0, 1, 1]]})}
    crop, evidence = body_image(row, tmp_path)
    assert crop.size == (80, 160)
    assert crop.getpixel((10, 20)) == (11, 22, 33)
    assert evidence['body_box_px'] == [10, 20, 90, 180]


def test_no_locator_does_not_silently_import_whole_card(tmp_path):
    Image.new('RGB', (100, 200)).save(tmp_path / 'card.png')
    with pytest.raises(ValueError, match='No valid body box'):
        body_image({'id': 1, 'file_name': 'card.png', 'print_meta': '{}'}, tmp_path)


def test_continuations_use_numeric_order_not_lexical_order():
    rows = [{'title': f'Solution ({n}/12)', 'position': 0, 'id': n} for n in [10, 2, 1]]
    assert [r['id'] for r in sorted(rows, key=part_order)] == [1, 2, 10]


def test_existing_solution_cannot_be_replaced_by_placeholder(tmp_path, monkeypatch):
    (tmp_path / 'figures').mkdir()
    (tmp_path / 'question.tex').write_text('Question', encoding='utf-8')
    (tmp_path / 'solution.tex').write_text(r'\textit{No solution provided.}', encoding='utf-8')
    monkeypatch.setitem(sys.modules, 'directory_manager', SimpleNamespace(get_question_dir=lambda *args: tmp_path))
    assert any('placeholder' in e for e in validate_item(1, '1.1', True))
    assert not validate_item(1, '1.1', False)


def test_unreferenced_and_wrong_side_figures_fail(tmp_path, monkeypatch):
    (tmp_path / 'figures').mkdir()
    (tmp_path / 'figures' / 'sfig1.png').write_bytes(b'image')
    (tmp_path / 'figures' / 'qfig9.png').write_bytes(b'image')
    (tmp_path / 'question.tex').write_text(r'Question \includegraphics{figures/sfig1.png}', encoding='utf-8')
    (tmp_path / 'solution.tex').write_text('No solution supplied', encoding='utf-8')
    monkeypatch.setitem(sys.modules, 'directory_manager', SimpleNamespace(get_question_dir=lambda *args: tmp_path))
    errors = validate_item(1, '1.1', False)
    assert any('Invalid side' in e for e in errors)
    assert any('Unreferenced figure qfig9' in e for e in errors)


def test_run_cannot_target_production_or_reference(tmp_path):
    cfg = tmp_path / 'bad.json'
    for dest in ['../', 'reference/PaperLab/runs/demo', 'C:/QP/PaperLab']:
        cfg.write_text(json.dumps({'run_dir': dest}), encoding='utf-8')
        with pytest.raises(ValueError): load_config(cfg)


def test_node3_can_report_a_genuine_taxonomy_gap():
    assert valid_classification({'codes': [], 'difficulty': 'Medium', 'suggestion': 'Numerical integration', 'errors': []})
    assert not valid_classification({'codes': [], 'difficulty': 'Medium', 'suggestion': None, 'errors': []})
    assert not valid_classification({'codes': ['PH01.01'], 'difficulty': None, 'errors': []})
