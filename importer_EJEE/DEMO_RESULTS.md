# Chapter demo results

Review: http://127.0.0.1:5183/archive/1

Imported textbook: **David Morin · Introduction to Classical Mechanics**, Chapter 1, **Strategies for solving problems**.

| Check | Result |
|---|---|
| Target | `runs/morin-chapter-01/paperlab.db`, paper ID 1 |
| Source | `C:/EJEE-data/ejee.db`, opened read-only including live WAL |
| Reference | Upstream commit `765b4d76201bba010ede1c573d7a0f3186311b01`, clean checkout |
| Question count | 18, original book labels 1.1–1.18 preserved in content/provenance |
| Question canvases | 18 lossless body pages |
| Worked solutions | 7 questions, 13 mapped image parts |
| Missing source solutions | 11 exercises explicitly marked “No solution provided”; none invented |
| Diagram PNGs | 5, exported from original pixels without enlargement |
| Fresh Node 3 | 18 calls; 19 auto topic links; one taxonomy-gap suggestion |
| Extraction accounting | 59 actual calls: 671,385 input, 343,343 cache-read, 22,908 output, 8,657 reasoning tokens |
| Node 3 accounting | 18 actual calls: 215,071 input, 161,070 cache-read, 9,288 output, 8,751 reasoning tokens |
| Total price estimate | USD 0.0457 using PaperLab's configured prices; not a provider billing statement |
| SQLite checks | Integrity and foreign keys passed |
| API checks | All 18 question detail responses, all 5 figure downloads, correct native question order and usage-ledger totals passed |
| Unit checks | 8 passed; runtime dependency check clean |

Node 3 correctly reported a taxonomy gap for the numerical Euler-integration problem (original question 1.7); its suggestion and Medium difficulty were preserved instead of forcing an unrelated topic. EJEE's previous topic and difficulty assignments were not imported.

The model's crop for original question 1.7 included small fragments of neighboring text. Visual review corrected that rectangle and saved it as a reusable, source-hash-checked crop. Future conversion of the same image can reuse this reviewed diagram without guessing its coordinates again.

The source database, main PaperLab application source, production database and production Outputs were not written by this import. All importer code, reference checkout, runtime, audit manifests and demo output live under `importer_EJEE`.

Full source-column disposition: [EJEE_COLUMN_MAPPING.md](EJEE_COLUMN_MAPPING.md), covering all 31 tables and every column. Selected source rows retain every original column in the run manifest; exam/student data is excluded from the target.

Machine-readable evidence: `verification.json`, `api_verification.json`, `progress.json`, `figure_export.json`, `data_normalizations.json`, individual tool traces and source asset hashes under the run directory. This is the completed chapter review demo; bulk import of other textbooks requires explicit numbering/part adapters and chapter review, and has not been run.

AI transcription and visual review do not establish character-perfect accuracy across every equation. Review the chapter in the app before approving a larger import. The native submission tools check syntax/references, rather than performing a full TeX compilation.
