# EJEE textbook importer

Convert a permitted copy of an EJEE SQLite export and its uploaded images
into PaperLab papers. The planner freezes book order into **15 importable
questions per paper by default** (the final part may be shorter). Papers are
named `<Book> — Part N`, with local numbers starting at 1. Source labels are
preserved in provenance. Missing or ambiguous source items are listed in the
plan; they are not guessed or silently inserted into later runs.

Prefer a UI? The [EJEE Importer app](app/README.md) is a separate local app
in PaperLab's style: search every EJEE question, convert whole books or
single parts, and publish them straight to a PaperLab server, with safe
pause/resume. It drives the same phases and run folders described below,
but it has no exclusion list and no human review step (it records an
explicit "no human review" approval). The CLI rules below are unchanged.

| Read next | What it contains |
|---|---|
| [EJEE Importer app](app/README.md) | Search, cart, process and publish without the command line |
| [EJEE_SOURCES.md](EJEE_SOURCES.md) | Source inventory, exclusions, all 13 live pilots, per-part costs, full-book estimates and the cache A/B test |
| [STATUS.md](STATUS.md) | Historical pilot handoff, known source defects and outstanding work |
| [Mapped extraction prompt](prompts/mapped_extractor.md) | The EJEE adapter to PaperLab's [base extractor prompt](../prompts/extractor_prompt.md) |
| [Custom importer](../custom_importer/README.md) · [agent skill](../custom_importer/SKILL.md) | For sources outside EJEE |
| [PaperLab bundle](../paperlab_bundle/README.md) | Shared export format, dry run and archive merge |

## Set up

Follow the [main installation guide](../README.md#2-install-and-configure).
All commands below run from the repository root using that Python 3.12
environment (`.venv/bin/python` on macOS/Linux;
`.\.venv\Scripts\python.exe` in PowerShell). The only extra inputs are
the **authorized EJEE database and upload tree**, which are not in Git.
Put them at `importer_EJEE/inputs/ejee.db` and
`importer_EJEE/inputs/uploads/`, or make a local copy of
[`books.json`](books.json) and edit its paths. Database and upload paths
in JSON are relative to the JSON file; `run_dir` is relative to
`importer_EJEE/`. Use forward slashes in Windows JSON paths.

Planning, review, repair, verification and merge do not call the model.
Only **extract** and **classify** require `META_API_KEY` and incur charges.
Start with one part, review it, then decide whether to scale up.

## 1. Plan and stage

```sh
python importer_EJEE/importer.py plan --config importer_EJEE/books.json
python importer_EJEE/run_book.py --config importer_EJEE/books.json --book "Hibbeler Dynamics 14e" --parts 1
```

Find the exact book name and slug in `importer_EJEE/runs/books/catalog.json`.
`run_book.py` can also plan just the selected book if its plan is absent.
It accepts `--parts 1-3` or `--parts 1,4,7`. The frozen plan and per-part
configuration, logs, and staged database are separate from the archive:

```text
importer_EJEE/runs/books/BOOK-SLUG/
  plan.json              stable membership and blocked source items
  part-001.json          configuration for individual phase commands
  part-001.log           phase logs
  last_run.json          status and estimated USD/INR/INR with GST
  part-001/              paperlab.db, Outputs/, sources/, verification, reviews
```

If the runner exits with status 2, read `last_run.json` and the part log.
Re-running the same command reuses prepared files and completed extraction.
If only tags need work, run `classify` and `verify` directly; do not rerun
extraction. New rows in EJEE are reported on re-plan but do not renumber an
existing plan. Keep the original plan with its staged parts.

### Individual phases

Use `python importer_EJEE/importer.py PHASE --config PART-CONFIG.json`.

| Phase | What it does |
|---|---|
| `inspect` / `plan` | Read the source schema and inventory, or freeze per-book plans |
| `prepare` | Materialize mapped question/solution image PDFs in the run |
| `extract` | Transcribe each item and crop figures; retries only unfinished or invalid items |
| `figures` / `pack` | Export source-pixel crops; apply local IDs and recorded rendering normalizations |
| `classify` | Run PaperLab's Node 3 for topics and difficulty, without importing EJEE classifications |
| `verify` | Write `verification.json`; refuse incomplete extraction or tagging, invalid text/media, source drift, and unresolved review holds |
| `repair` / `approve` | Repair crops without the model, then record human approval against exact file hashes |
| `export` | Verify again and write a `.plbundle`, including source refs, usage counters, reviews and verification |

## 2. Review and repair

Build the frontend with `npm --prefix frontend run build` (Windows:
`npm.cmd`). Set `PAPERLAB_ADMIN_PASSWORD` to a strong value of at least 12
characters in the shell running the launcher, then pass the directories
containing staged `paperlab.db` files:

```sh
python importer_EJEE/serve_review.py --port 8020 --sources "importer_EJEE/runs/books/BOOK-SLUG/part-001"
```

Open **http://127.0.0.1:8020/** and select **Archive**. The launcher copies the selected
runs and disables paid calls. UI edits affect only the copy; apply
corrections to the actual staging run before exporting. Keep the review
server on loopback: the reading routes are not password-protected. Stop it
before rebuilding the copy. Without `--sources`, it will look for local
pilot runs; no pilot artifacts are included in Git.

```sh
python importer_EJEE/importer.py repair --config PART-CONFIG.json
python importer_EJEE/importer.py repair --config PART-CONFIG.json --by "Reviewer name" --pick "10/sfig1.png=bottom-out"
python importer_EJEE/importer.py approve --config PART-CONFIG.json --by "Reviewer name" --note "Compared the crop and text with the complete source page"
```

`repair` produces comparison sheets and measured alternatives. Compare
the crop with the full source image, including labels, captions that are
part of the diagram and handwritten marks. A clean edge score is not
proof of completeness. Picks are tied to the source hash; any changed TeX
or figure invalidates its previous approval. Preserve all source content,
including handwriting and continuations; mark illegible content
`[UNREADABLE]` instead of filling it in. Never solve or silently correct
the source.

## 3. Export and merge

```sh
python importer_EJEE/importer.py export --config PART-CONFIG.json --out hibbeler-part-1.plbundle
python -m paperlab_bundle inspect hibbeler-part-1.plbundle
python -m paperlab_bundle merge hibbeler-part-1.plbundle --target-db physics_archive.db --dry-run --require-reviewed
python -m paperlab_bundle merge hibbeler-part-1.plbundle --target-db physics_archive.db --require-reviewed
```

Read the [merge guide](../paperlab_bundle/README.md) before publishing.
Specify `--target-outputs` when the archive does not use the `Outputs`
folder beside its database. The EJEE `merge` phase is a convenience wrapper
around the same merger and requires an explicit target.
For a deployed host without shell access, use the
[archivist upload API](../paperlab_bundle/README.md#upload-to-a-deployed-server)
with the same `.plbundle`.

## Pilot evidence and cost

The contribution reports **18 paid pilot parts (270 questions)**:
13 earlier pilots (~US$0.69) plus 5 app pilots of institute material, test
papers and an actual JEE Advanced paper (~US$0.32), each published direct.
The full conversion scope is **~US$249 / ₹23,100 / ₹27,257 including 18%
GST**, using ₹92.89/USD (22 Nov 2026). These are historical measurements and projections,
not a quote or a guarantee. See the [pilot tables and cost methodology](EJEE_SOURCES.md)
for source-specific results, holds, and the separate cache experiment.
`USD_INR` overrides the runner's display rate. For new conversions,
fix held crops with `repair` rather than paying to regenerate them.

Optional free checks: `validate_assets.py` verifies planned source images
and `support_check.py` runs `prepare` on each planned book's first part.
Both accept the same `--config` as the planner. To run the isolated, no-key
regression suite:

```sh
python scripts/test_backend.py -q
```
