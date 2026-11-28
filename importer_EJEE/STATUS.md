# Status: EJEE → PaperLab importers

Historical handoff from the November 2026 EJEE pilots. For current setup and
commands, use the [EJEE importer README](README.md). This snapshot preserves
the pilot evidence, changes and costs (USD, INR, INR incl. 18% GST).
Rupee figures use ₹92.89 per USD (22 Nov 2026).

## 1. What exists

| Piece | Folder | Purpose |
|---|---|---|
| EJEE textbook importer | `importer_EJEE/` | Books already in the EJEE database → PaperLab papers named `TBname — Part N`, ~15 questions each. EJEE DB and uploads are read-only. |
| Custom importer | `custom_importer/` | Books not in EJEE: a person or agent transcribes and crops; PaperLab's own savers and validators stage it. |
| Universal bundle + merger | `paperlab_bundle/` | One portable `.plbundle` file (zip: `bundle.json`, `paperlab.db` with relative paths, `Outputs/`, `sources/`, SHA-256 per file). Both importers export it; one merger imports it into any archive on Windows, macOS or Linux. |

Nothing reaches an archive without an explicit merge. EJEE export requires a
passing verification report. The shared bundle merger reports carried review
findings as warnings unless `--require-reviewed` is set.

## 2. Converted and held so far

13 pilot parts, 195 questions, all staged: Physics Galaxy, Hibbeler, Meriam &
Kraige, Irodov, Young & Freedman, APhO, PYQ+, BIIT, Sardana, SBT, JEE Digital,
INSP, Aakash. The owner reviews staged parts before publication.
Per-part costs and notes: [EJEE_SOURCES.md](EJEE_SOURCES.md) §4–5.

Known source problems (EJEE data, left blocked on purpose): Y&F Part 3 Q8 and
APhO Part 1 Q4. APhO Q6 was approved by the user.

Aakash Book Crunch 1, Part 1 was re-run with the cache fix (§4). The user
approved the new run; it is now the official `part-001`, exported as a
bundle with nothing pending. The earlier run is kept outside the repo as a
backup.

## 3. Changes in this round

**Crops**
- `importer.py repair` fixes held or flagged figures with **no AI cost**. It
  draws candidate sheets with measured options: per-edge moves (`top-in`,
  `bottom-out`, …) and combined `expand`/`shrink`. `--pick Q/fig=option --by NAME`
  records the chosen rectangle in the run's `reviewed_crops.json`, bound to the
  source image hash so it survives re-runs. A human must approve the new PNGs.
- Crop replies to the model now also list per-edge options, so one edge can
  drop a caption while another keeps a cut label.
- Pilot review: every figure that touched an edge ("a lil cut" labels) was
  fixed with `repair`: 4 in the first Aakash run, 5 in the re-run.

**Prompts** (read end to end as the model receives them; no contradictions left)
- Core directives numbered 1–4 again.
- An imperfect figure no longer stops the question: the model saves the
  transcription and the importer holds the figure for review.
- Removed references to base-prompt sections that do not exist, and the rule
  that a computed answer decides the question type (type follows the required
  response format).
- Saving instructions defer to the SAVING section.

**Rendering**
- Plain-TeX `\eqno{(1)}` / `\eqno{\text{...(3)}}` showed as red errors in the
  web view. `pack` now converts them to `\tag*{…}` in displays (printed label
  kept exactly) or plain text after prose. `verify` refuses any leftover `\eqno`.
- Fixed `verify`'s `$$ … \tag` check, which paired `$$` wrongly.

**Cost** (details in §4)
- The extraction conversation is append-only by default; pruning old crop
  previews is opt-in (`prune_previews: true`).
- `run_book.py` prints and records each part's cost in USD, INR and INR
  incl. 18% GST (`USD_INR` env var overrides the rate).

**Other**
- `load_config` accepts a UTF-8 BOM (configs saved by Notepad/PowerShell).
- `serve_review.py` can show two runs of the same part side by side.
- Current setup uses the root `requirements.txt`; the old demo and sample
  workflow has been retired. `--config` is required for individual phases.
- Tests: 93 pass (`importer_EJEE`, `custom_importer`, `paperlab_bundle`).

## 4. Cost

Measured on the 13 pilots: about half the extraction money ($0.31 of $0.61)
went on input the provider had seen before but did not serve from cache.
Pruning old previews rewrote earlier messages and broke the cache on every
re-crop. The A/B re-run of Aakash Part 1:

| | Calls | Crops | Extraction cached | Extraction | Total | Total INR | INR incl. GST |
|---|---:|---:|---:|---:|---:|---:|---:|
| Pruning (old) | 119 | 108 | 64% | $0.0747 | $0.0785 | ₹7.29 | ₹8.60 |
| Append-only (now) | 109 | 93 | 73% | $0.0729 | $0.0837 | ₹7.77 | ₹9.17 |

Cache breaks fell from 22 calls to 1, but kept previews made prompts 25%
larger, so extraction is only ~2% cheaper. The total rose because the
unchanged topic-tagging step got a poor cache rate from the provider that run
(96% → 57%). The projections therefore keep the measured pilot rates.

| Scope | Questions | USD | INR | INR incl. 18% GST |
|---|---:|---:|---:|---:|
| Textbooks | 39,535 | ~$106 | ₹9,842 | ₹11,614 |
| Institute test papers | 15,325 | ~$77 | ₹7,119 | ₹8,401 |
| Institute study material (incl. Allen) | 20,574 | ~$43 | ₹3,973 | ₹4,689 |
| Past-year, exam papers, olympiads | 6,348 | ~$21 | ₹1,924 | ₹2,271 |
| **Everything convertible** | **81,782** | **~$249** | **₹23,100** | **₹27,257** |

Per 15-question part incl. GST: ~₹2 for key-only cards, ₹3–6 for printed
books and institute sheets, ~₹6 for an Allen module, ~₹9 for Aakash, ~₹24
for a photo olympiad. Session spend so far ≈ $2.01 (≈₹187, ₹220 incl. GST):
$1.68 on the earlier pilots and cache A/B, $0.32 on the five app pilots
below. The old "~$170"/"~$150 (Allen excluded)" figures predate user
approval to convert institute material and test papers.

What was considered and **not** done, to protect quality: lowering the crop
cap from 8 to 6 attempts, and smaller preview images.

## 5. Rules (unchanged)

Transcribe, never solve; `[UNREADABLE]` instead of guessing. Figures are
original pixels only, cropped with `exact_crop`. Nothing is dropped silently.
The CLI rules are unchanged: holds block EJEE export until a human approves
the exact files, and `run_book.py` still refuses institute test papers and
actual JEE Advanced papers. The app converts everything and publishes
directly (held figures approved automatically as "no human review").

## 6. Not verified / open

- The live paid pilots used the contributor's Windows environment. Current
  offline import and bundle checks run in PaperLab's macOS/Linux/Windows CI
  matrix; macOS and Linux are required, Windows advisory.
- One A/B run is a small sample; provider cache variance is larger than the
  ~2% gain.

## 7. Next

Both items from the pilot handoff are now done:

1. **EJEE Importer app** ([app/README.md](app/README.md)): a separate local
   app in PaperLab's style. It searches every EJEE question from every
   source (institute material and test papers included, all convertible),
   converts whole books or single 15-question parts, and publishes each
   part straight to a PaperLab server. There is no review step: held
   figures get an approval recorded as "automatic, no human review". A
   wrong key, link or password pauses the queue, and resume continues at
   the step that stopped.
2. **HTTP handoff**: PaperLab's `POST /api/bundles/import` (upstream). The
   app uses it; a live check against a scratch archive published the
   Meriam pilot bundle once and returned `already_imported` on a repeat.

Open: the app's live checks ran on Windows; macOS and Linux are covered by
the offline tests in CI only. No full paid run through the app yet; the
first one should be a single cheap part (e.g. a BIIT part, ~₹2 incl. GST).
