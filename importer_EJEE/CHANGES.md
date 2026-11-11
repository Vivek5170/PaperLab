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
