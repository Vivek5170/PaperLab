# EJEE importer contribution: complete change record

This contribution adds `importer_EJEE/` only. It does not change PaperLab's application source, schema, extractor implementation or prompts. Existing unrelated edits in the contributor's working repository are excluded from this pull request.

## Data model and isolation

- Inspect EJEE SQLite databases in read-only/query-only transactions, including the live WAL.
- Document every column of all 31 tables observed in the full EJEE source database; distinguish content/provenance from worksheet UI state, exam administration and student data.
- Join questions and all solution continuations by exact `(source, grp)`, preserving numeric continuation order. Reject missing assets, unsupported roles and ambiguous mappings.
- Resolve textbook chapters with an explicit named-group regex, rather than treating EJEE's teaching-topic tree as the book's chapter order. Support exact group allowlists for small chapter excerpts.
- Store one textbook chapter as one PaperLab paper, with the exact textbook name as `source_institute`, `exam_type=Textbook`, real image-PDF paths and no invented exam date.
- Use chapter-local numeric target question IDs for correct sorting in the unchanged reader. Preserve original book labels and source records in provenance.
- Put all writable databases, generated assets, progress and traces under the importer. Refuse run paths outside it or inside the reference checkout.

## Node 2 adaptation

- Load the upstream extractor prompt and append a mapped-question adapter. Skip indexing and full-document searches because EJEE already supplies question/solution mappings.
- Crop existing image card bodies losslessly using validated `print_meta.box` coordinates. Wrap the resulting pixels in PDF pages so upstream PDF-based tools remain usable.
- Reuse the actual upstream `get_page_image`, `assisted_crop`, `exact_crop`, `submit_question` and `submit_solution` tools. Preserve image-bearing HumanMessage results and the original crop retry gates.
- Restrict tool calls to the fixed paper, question, PDF and mapped page allowlist. Keep question/solution figure prefixes separate.
- Preserve complete statements, equations, subparts, options and diagrams. Do not invent answers or worked solutions. Use the native explicit missing-solution placeholder where no mapped explanation exists.
- Omit source question numbers, descriptive titles and difficulty stars from displayed question content, per the final requested policy. Retain them in the source manifest. A deterministic cleanup handles headings sharing a line with the first sentence without removing that sentence.
- Disable the vector-oriented 600 dpi save for raster canvases and export accepted diagram rectangles directly from original pixels. Record source hashes, final boxes and output hashes.
- Add a reviewed crop cache keyed by exact source-body hash; include a manually reviewed correction removing foreign text from Morin 1.7. Reuse valid reviewed coordinates without asking the model to guess them again.
- Save bounded, resumable per-question traces without base64 images or credentials.

## Node 3 and accounting

- Run upstream `run_topics.classify_question` afresh on the converted TeX using upstream's prompt and topic hierarchy. Do not copy EJEE topics, difficulty or suggestions into target classification.
- Accept the native valid taxonomy-gap result (no topic link with a new-topic suggestion), rather than forcing unrelated topics.
- Log real extractor and Node 3 token usage in native `token_usage`, including cached-input and reasoning counters. Preserve native topic ranks/src fields, difficulty, paper status and elapsed time.
- Resume completed items and fresh classifications without repeating paid work. Provide a configured-price cost report; do not claim it is a provider invoice.

## Author test package

- Include `sample_data/paperlab.db`: 22 questions in three chapter entries from two textbooks, with 7 diagram PNGs and fresh Node 3 results.
- Morin Chapter 1 is complete (18 questions); Morin Chapter 2 and Hibbeler Chapter 12 are explicitly labeled two-question excerpts, not complete chapters.
- Include a minimal EJEE input fixture, only the 40 selected question/solution resource records and their required taxonomy ancestors, plus the referenced source images. No student records, exam responses, credentials, complete textbook PDFs or live production database are included.
- Keep paths relative in the distributed database. `serve_sample.py` copies it to a separate writable review directory and rebases paths on the reviewer's computer. Browsing the converted sample makes no AI calls and needs no API key.
- Include portable configs for reproducing conversion from the minimal EJEE fixture. New conversion uses the reviewer's own Meta credential; no contributor key is distributed.
- Support both a standalone local reference checkout and installation inside the author's normal PaperLab checkout, without recursive cloning or application edits.

## Validation and limits

Check read-only source access, lossless body cropping, continuation ordering, run-directory isolation, missing solutions, incorrect/unreferenced figure paths, heading cleanup and valid Node 3 taxonomy gaps. Verify bundle integrity, native foreign keys, all question files and PNG references, relative paths and absence of exam/student tables. Check the running sample API and native usage ledger separately.

AI transcription still needs review for source fidelity. Native submission validates syntax/references; it does not prove a full TeX compile. Eleven Morin Chapter 1 exercises lack mapped source solutions. The importer does not fabricate them. Additional books need explicit validated chapter/part adapters; this contribution does not bulk-import all EJEE content.

Earlier local work also repaired the contributor's main app startup by deferring optional extraction imports. That pre-existing local edit is **not included** here; the PR contains only the independent importer and test package.

## Rendering compatibility correction

Normalize plain-TeX equation labels (`\eqno(1.21)`) into browser-supported `\tag{1.21}`. Preserve literal program operators, comments and line order by converting verbatim blocks to monospace math arrays: the unchanged native renderer otherwise strips the verbatim wrapper and Markdown merges/italicizes code. Apply normalization both before native submission and during packing; update existing demo and bundled sample files. No application-source edits or additional AI calls are required. Regression coverage exercises the actual upstream TeX/HTML bridge, and 307 rendered math segments pass KaTeX with throwOnError enabled.

## Deterministic source-boilerplate handling (no extra AI calls)

The EJEE source is fixed (Subjective UI tags, card body boxes without footer
footnotes, margin key markers, caption lines, comma-laid options, dotted
printed labels), so everything mechanical is code, not model turns: pack and
pre-submit normalization strip hfill-Ans markers, standalone/glued Fig.
caption lines, and verified printed solution headings; tagged displays become
equation environments (real LaTeX rejects \tag inside $$); Answer/Solution-for
IDs are rewritten to the fixed local number; footnotes whose bodies fall
outside the body box are dropped with no meta-notes; option lists use
enumerate even when the source lays them out as comma displays. pack
compile-checks every rewritten file with upstream verify_latex_syntax,
remaps figure_export IDs, and warns when classified tex changed after
classify; verify asserts per-question qtype membership; group_pattern is
validated up front. The QTYPE signal comes from the question's own structure
(base-prompt codes and decision order retained); source_qtype is ignored.

## Explicit passage merges, classify invalidation, review-copy freshness

- Passage groups split across EJEE groups are merged only by explicit
  `merge_groups: {"3-5_paragraph": [...]}` config: validated (known groups,
  no double-listing, no number collisions, allowlist agreement), concatenated
  in listed order, paragraph IDs bypass single-group re-derivation in pack,
  per-sub labels range-checked. Unlisted splits stay separate (fail-open).
  `paragraph_range()` gates the local-ID rewrite/validator for group IDs.
- `classify` fingerprints the topics seed, topic prompt and upstream commit
  into progress (`node3_meta`); any change discards cached auto tags and
  re-runs loudly instead of silently keeping stale ones.
- `serve_sample.py` stamps the review copy with the bundle hash and rebuilds
  on mismatch (plus `--fresh`), asserts portable relative paths before
  rebasing, and runs integrity/foreign-key checks after copy.
- `build_sample.py` takes `--runs/--source-db/--uploads` (old hardcoded
  author paths are now just defaults). Bundle tests pin coverage
  (>= per-question usage rows, >= 7 figures) instead of exact totals, so a
  valid repair no longer fails the suite; exact totals stay informational.
