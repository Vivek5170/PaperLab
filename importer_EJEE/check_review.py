"""Check the running, unchanged PaperLab API through the review frontend proxy."""
import json
import os
from bootstrap import ROOT, activate

run = activate(ROOT / 'runs/morin-chapter-01')
import httpx
from app.auth import _configured_password

manifest = json.loads((run / 'manifest.json').read_text(encoding='utf-8'))
verification = json.loads((run / 'verification.json').read_text(encoding='utf-8'))
base = 'http://127.0.0.1:5183'
with httpx.Client(base_url=base, timeout=30) as client:
    page = client.get('/archive/1'); page.raise_for_status()
    paper = client.get('/api/papers/1'); paper.raise_for_status(); paper = paper.json()
    assert paper['institute'] == manifest['config']['book_source']
    assert paper['status'] == 'done' and not paper['error']
    questions = client.get('/api/papers/1/questions'); questions.raise_for_status(); questions = questions.json()
    assert [q['number'] for q in questions] == [str(n) for n in range(1, 19)]
    figure_count = 0
    for item in manifest['items']:
        number = item['number']
        response = client.get(f'/api/papers/1/questions/{number}'); response.raise_for_status()
        assert '*missing*' not in response.text
        for path in (run / 'Outputs' / '1' / number / 'figures').glob('*.png'):
            response = client.get(f'/api/papers/1/questions/{number}/figures/{path.name}')
            response.raise_for_status(); assert response.headers['content-type'].startswith('image/')
            figure_count += 1
    response = client.post('/api/auth/login', json={'password': _configured_password()}); response.raise_for_status()
    try:
        response = client.get('/api/stats'); response.raise_for_status(); stats = response.json()
        assert stats['turns'] == sum(r['calls'] for r in verification['usage'])
        assert {p['phase'] for p in stats['phases']} == {'extractor', 'topics'}
        assert not stats['errors']
    finally:
        client.post('/api/auth/logout').raise_for_status()
    report = {'ok': True, 'url': base+'/archive/1', 'questions': len(questions),
              'figure_downloads': figure_count, 'stats_turns': stats['turns'],
              'estimated_cost_usd': sum(row['total'] for row in stats['rows']),
              'native_question_order': [q['number'] for q in questions]}
(run / 'api_verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report, indent=2))
