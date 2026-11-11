# Phased implementation

## 1. Audit and contract

Download upstream `Vivek5170/PaperLab` under `reference/PaperLab`; pin its commit in every manifest. Treat this checkout as read-only. Inspect EJEE in SQLite read-only/query-only mode, including its active WAL, using one transaction per export. Record the complete schema and table counts without exporting student records.

The current source has `resources`, not `tb_chapter`. A textbook adapter must declare an exact source and a group regex with chapter/number captures. For Morin, `morin-1.1` means chapter 1, question 1.1. This is independent of teaching-topic ancestry: a chapter may cover many topics. Never infer a book chapter from an EJEE topic.

## 2. Deterministic source preparation

Join all question and solution parts by `(source, grp)`, preserving continuation order. Preserve every selected resource column and its original node ancestry in `manifest.json`; retain matching crop/transcript records. Fail on missing assets, ambiguous duplicate questions or unsupported part roles. Use original `file_name`, not enhanced alternatives silently.

`print_meta.box` is an existing normalized rectangle around the card body, not an isolated figure. Crop that body losslessly, recording input/output SHA-256, dimensions and pixel coordinates. Keep key/mask/qn rectangles as provenance, never reuse them as diagram coordinates. Build separate chapter question/solution PDFs by inserting each body PNG without resampling, so upstream PDF crop tools can operate unchanged. Map every PDF page back to the source resource. All new files stay under the run directory.

Explicit `resource_crops.role=diagram/solution_diagram` records are candidates for future reuse only after source identity, coordinate frame, boundaries and side are verified. None are present for the demo; there are just three generic question-region records in the entire source database. Do not claim these as perfect figure crops.

## 3. Adapt Node 2 per mapped question

Reuse upstream extractor prompt and the actual `get_page_image`, `assisted_crop`, `exact_crop`, `submit_question`, `submit_solution` implementations. Append a documented adapter for mapped raster pages: no indexing, shared-key assumptions or document-wide scanning. Supply the known question/solution images immediately. Restrict every model tool invocation to the fixed paper ID, question ID and page allowlist. Preserve crop retry limits, preview feedback, stable figure names and qfig/sfig separation.

Only convert text/math to LaTeX and isolate printed diagrams. Do not solve, invent missing answers, or manufacture diagram art. A proof/symbolic textbook problem may remain `unknown` because PaperLab's qtype vocabulary has no subjective code. Missing source solutions use the native explicit placeholder. Existing worked solutions may never be replaced with that placeholder.

Use the existing PaperLab Meta credential in memory. No credential is copied into importer files or traces. Use a separate compatible Python runtime; do not change the main app environment or Windows security settings.

## 4. Fresh Node 3 and accounting

Call the upstream `run_topics.classify_question` against the imported TeX, upstream seed hierarchy and original prompt. Do not import old topics, difficulty or suggestions. Require valid fresh difficulty plus either topic links or an explicit taxonomy-gap suggestion. Node 3's own implementation writes `question_topics(src=auto)`, difficulty/suggestions and `token_usage(phase=topics)`.

Log every successful Node 2 model response using `database.log_token_usage(phase=extractor)` with actual input, cache-read, output and reasoning counts. Never invent historical EJEE cost or indexing calls. PaperLab derives costs from these rows and its configured prices. Record per-question elapsed time/turns in importer progress and paper elapsed time/status in native columns; leave question status at the native submitter's draft default.

## 5. Chapter demo and review

Import all 18 Morin chapter 1 questions, including every mapped solution part. Check counts, TeX, referenced PNG existence, unreferenced PNGs, qfig/sfig separation, unchanged source hashes, SQLite integrity/foreign keys, actual token rows and fresh Node 3 completion. Start an independent API and upstream frontend on ports 8011/5183, using only this run's database/Outputs/data. Keep the existing desktop app on its original ports.

After the native crop loop, export final raster boxes directly from original source pixels: upstream's vector-oriented 600 dpi save would enlarge these 200 dpi image canvases. Visual review found foreign text fragments on one crop's left edge; a corrected pixel rectangle is stored in `reviewed_crops_demo.json`, keyed by exact source-body SHA-256, and is reused without another model coordinate guess. Five diagrams were inspected against their body images.

Use chapter-local numeric IDs for native reader ordering and preserve original labels (1.1, 1.2, etc.) in the TeX and manifest. Encode literal printed heading stars outside the bold wrapper to avoid the native Markdown bridge producing broken emphasis. These are data transformations, recorded separately, with no upstream source changes.

## 6. Bulk expansion after chapter review

Add explicit adapters for each additional textbook numbering convention, answer-key representation and continuation layout. Detect uncertain chapter membership and mapping gaps instead of silently importing them. Reuse reviewed diagram locators where present; introduce a separate reviewed figure cache keyed by source image hash + crop coordinates if repeated imports justify it. Resume completed items and never repeat paid conversion for an unchanged source. Production import remains a separate reviewed operation; no production data is written by this demo.
