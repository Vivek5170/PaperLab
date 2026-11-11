# Chapter import cost analysis

| Stage | Calls | Fresh input | Cached input | Output | Estimated USD |
|---|---:|---:|---:|---:|---:|
| extractor | 59 | 328,042 | 343,343 | 22,908 | $0.038072 |
| topics | 18 | 54,001 | 161,070 | 9,288 | $0.007580 |

Total: **$0.045652**, or **INR 4.3370** at the configured conversion of INR 95/USD.

Average over 18 questions: $0.002536, INR 0.2409.

Configured rates per million tokens: fresh input $0.10, cached input $0.002, output $0.20. These are the existing app settings, not independently verified current provider prices.

All 59 extractor turns include their tool/crop feedback loops. The 18 topics calls are fresh upstream Node 3 classifications. Indexing was skipped and has no charge recorded. Diagram pixel export, heading cleanup and this report made no model calls.

Recorded Meta API usage for the isolated chapter; excludes Codex session, local compute and any unrecorded failed requests. Configured-price estimate, not a provider invoice. Reasoning tokens are reported separately for visibility but are not added again to output cost.