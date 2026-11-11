"""Report recorded API usage at the configured PaperLab prices, without API calls."""
import json
from bootstrap import ROOT, activate

run = activate(ROOT / 'runs/morin-chapter-01')
import config
import database

with database.get_connection() as c:
    rows = [dict(r) for r in c.execute('SELECT phase,count(*) calls,sum(input) input,sum(cache_read) cached,sum(output) output,sum(reasoning) reasoning FROM token_usage GROUP BY phase')]
total = 0
for row in rows:
    row['fresh_input'] = row['input'] - row['cached']
    row['input_cost_usd'] = row['fresh_input'] * config.PRICING['input_per_mtok'] / 1e6
    row['cached_cost_usd'] = row['cached'] * config.PRICING['cache_read_per_mtok'] / 1e6
    row['output_cost_usd'] = row['output'] * config.PRICING['output_per_mtok'] / 1e6
    row['total_usd'] = sum(row[k] for k in ['input_cost_usd', 'cached_cost_usd', 'output_cost_usd'])
    total += row['total_usd']
report = {'phases': rows, 'total_usd': total, 'total_inr': total * config.USD_TO_INR,
          'per_question_usd': total / 18, 'per_question_inr': total * config.USD_TO_INR / 18,
          'pricing_per_million_tokens': config.PRICING, 'configured_usd_to_inr': config.USD_TO_INR,
          'scope': 'Recorded Meta API usage for the isolated chapter; excludes Codex session, local compute and any unrecorded failed requests. Configured-price estimate, not a provider invoice. Reasoning tokens are reported separately for visibility but are not added again to output cost.'}
(run / 'cost_analysis.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
lines = ['# Chapter import cost analysis', '', '| Stage | Calls | Fresh input | Cached input | Output | Estimated USD |', '|---|---:|---:|---:|---:|---:|']
for r in rows:
    lines.append(f'| {r["phase"]} | {r["calls"]} | {r["fresh_input"]:,} | {r["cached"]:,} | {r["output"]:,} | ${r["total_usd"]:.6f} |')
lines += ['', f'Total: **${total:.6f}**, or **INR {total*config.USD_TO_INR:.4f}** at the configured conversion of INR {config.USD_TO_INR:g}/USD.', '',
          f'Average over 18 questions: ${total/18:.6f}, INR {total*config.USD_TO_INR/18:.4f}.', '',
          'Configured rates per million tokens: fresh input $0.10, cached input $0.002, output $0.20. These are the existing app settings, not independently verified current provider prices.', '',
          'All 59 extractor turns include their tool/crop feedback loops. The 18 topics calls are fresh upstream Node 3 classifications. Indexing was skipped and has no charge recorded. Diagram pixel export, heading cleanup and this report made no model calls.', '', report['scope']]
(ROOT / 'COST_ANALYSIS.md').write_text('\n'.join(lines), encoding='utf-8')
print(json.dumps(report, indent=2))
