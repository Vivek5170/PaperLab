"""Build the public, portable three-chapter fixture from completed isolated runs."""
import json
from pathlib import Path
import re
import shutil
import sqlite3
from bootstrap import ROOT

RUNS = ['morin-chapter-01', 'morin-chapter-02-sample', 'hibbeler-chapter-12-sample']
out = ROOT / 'sample_data'
if out.exists(): raise SystemExit('sample_data already exists; choose a fresh build destination rather than overwriting')
out.mkdir()
manifests = [json.loads((ROOT/'runs'/name/'manifest.json').read_text(encoding='utf-8')) for name in RUNS]
with sqlite3.connect(ROOT/'runs'/RUNS[0]/'paperlab.db') as src, sqlite3.connect(out/'paperlab.db') as target:
    src.backup(target)


def insert(c, table, row):
    row = {k:v for k,v in row.items() if k != 'id'}
    return c.execute('INSERT INTO '+table+' ('+','.join(row)+') VALUES ('+','.join('?' for _ in row)+')', list(row.values())).lastrowid


summary = []
with sqlite3.connect(out/'paperlab.db') as target:
    target.row_factory = sqlite3.Row
    for newpid,(name,manifest) in enumerate(zip(RUNS,manifests),1):
        run = ROOT/'runs'/name
        with sqlite3.connect(run/'paperlab.db') as src:
            src.row_factory = sqlite3.Row
            if newpid != 1:
                pid = insert(target, 'papers', dict(src.execute('SELECT * FROM papers').fetchone()))
                assert pid == newpid
                for row in src.execute('SELECT * FROM questions'):
                    qid = row['id']; r = dict(row); r['paper_id'] = newpid
                    newqid = insert(target, 'questions', r)
                    for link in src.execute('SELECT * FROM question_topics WHERE question_id=?',(qid,)):
                        link = dict(link); link['question_id'] = newqid; insert(target,'question_topics',link)
                for row in src.execute('SELECT * FROM token_usage'):
                    row = dict(row); row['paper_id'] = newpid; insert(target,'token_usage',row)
        shutil.copytree(run/'Outputs'/'1', out/'Outputs'/str(newpid))
        shutil.copytree(run/'sources', out/'data'/'sources'/str(newpid))
        qp = f'data/sources/{newpid}/questions.pdf'
        sp = f'data/sources/{newpid}/solutions.pdf' if manifest['solution_pdf'] else None
        target.execute('UPDATE papers SET question_pdf_path=?,solution_pdf_path=? WHERE id=?',(qp,sp,newpid))
        for item in manifest['items']:
            target.execute('UPDATE questions SET latex_folder=? WHERE paper_id=? AND question_number=?',(f'Outputs/{newpid}/{item["number"]}',newpid,item['number']))
        # Remove workstation-specific paths from public audit metadata.
        text = json.dumps(manifest, ensure_ascii=False)
        for key,value in [(str(run), '.'), (str(ROOT), 'importer_EJEE'), ('C:/EJEE-data', 'EJEE-source'), ('C:\\EJEE-data','EJEE-source')]:
            text = text.replace(json.dumps(key)[1:-1], json.dumps(value)[1:-1])
        dest = out/'provenance'/f'paper-{newpid}.json'; dest.parent.mkdir(exist_ok=True)
        dest.write_text(text,encoding='utf-8')
        for meta in (out/'Outputs'/str(newpid)).rglob('_import_provenance.json'):
            text = meta.read_text(encoding='utf-8')
            text = text.replace(json.dumps(str(run/'sources'))[1:-1], f'data/sources/{newpid}')
            meta.write_text(text,encoding='utf-8')
        cfg = dict(manifest['config'])
        cfg.update(source_db='../ejee_sample.db', asset_root='../source_assets', run_dir='runs/reproduce-'+name)
        cfg.pop('original_pdf',None)
        (out/'configs').mkdir(exist_ok=True)
        (out/'configs'/f'{name}.json').write_text(json.dumps(cfg,indent=2,ensure_ascii=False),encoding='utf-8')
        summary.append({'paper_id':newpid,'book':cfg['book_source'],'chapter':cfg['chapter'],'title':cfg['chapter_title'],
                        'questions':len(manifest['items']), 'full_chapter':newpid==1,
                        'source_groups':[i['group'] for i in manifest['items']]})

# EJEE input fixture contains only the selected resources and node ancestors.
resources = {r['id']:r for m in manifests for i in m['items'] for side in ('question','solution') for r in i[side+'_rows']}
nodes = {n['id']:n for m in manifests for i in m['items'] for lineage in i['original_ancestry'].values() for n in lineage}
raw = sqlite3.connect('file:C:/EJEE-data/ejee.db?mode=ro',uri=True); raw.row_factory=sqlite3.Row
with sqlite3.connect(out/'ejee_sample.db') as fixture:
    for table in ('nodes','resources','source_documents','resource_crops','resource_transcripts'):
        fixture.execute(raw.execute('SELECT sql FROM sqlite_master WHERE name=?',(table,)).fetchone()[0])
    for table,rows in [('nodes',nodes),('resources',resources)]:
        cols = [r[1] for r in raw.execute('PRAGMA table_info('+table+')')]
        for row in rows.values():
            fixture.execute('INSERT INTO '+table+' ('+','.join(cols)+') VALUES ('+','.join('?' for _ in cols)+')',[row.get(k) for k in cols])
            if table == 'resources':
                (out/'source_assets').mkdir(exist_ok=True)
                shutil.copy2(Path('C:/EJEE-data/uploads')/row['file_name'], out/'source_assets'/row['file_name'])
raw.close()
with sqlite3.connect(out/'paperlab.db') as c:
    usage = [dict(zip(['phase','calls','input','cached','output','reasoning'],r)) for r in c.execute('SELECT phase,count(*),sum(input),sum(cache_read),sum(output),sum(reasoning) FROM token_usage GROUP BY phase')]
    assert c.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert not c.execute('PRAGMA foreign_key_check').fetchall()
report={'papers':summary,'questions':sum(p['questions'] for p in summary),'usage':usage,
        'contains_student_data':False,'sample_scope':'One full chapter and two two-question chapter excerpts; no full textbook PDFs.'}
(out/'manifest.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(report,indent=2,ensure_ascii=True))
