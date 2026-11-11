# EJEE importer and portable author test dataset

This contribution adds only `importer_EJEE/`, with no changes to PaperLab's application source. See [CHANGES.md](CHANGES.md) for the complete change record, [UPSTREAM_ANALYSIS.md](UPSTREAM_ANALYSIS.md) for the extractor/prompt/tools analysis, and [EJEE_COLUMN_MAPPING.md](EJEE_COLUMN_MAPPING.md) for every source table/column disposition.

**Start with [sample_data/README.md](sample_data/README.md)** for exact launch and reproduction commands. The package contains 22 questions across three chapter entries from two books: full Morin Chapter 1, a two-question Morin Chapter 2 excerpt, and a two-question Hibbeler Chapter 12 excerpt. Seven diagram PNGs, mapped explanations, fresh upstream Node 3 results and 94 actual usage rows are included. The minimal EJEE input fixture contains 40 selected resource parts with their source images and taxonomy ancestors; no student/exam records, full textbook PDFs, production data or credentials are included.

Browsing the converted sample requires no API calls or key. `serve_sample.py --port 8001` copies the fixture into a separate writable review directory and rebases paths on the reviewer's machine; run the existing frontend normally on 5173. New conversions use the reviewer's own `META_API_KEY` and make paid requests. Relative config paths resolve from the config directory; generated run directories must stay inside this importer.

Run read-only fixture verification with `python importer_EJEE/sample_data/verify.py`. After installing `requirements.txt` in an isolated environment, run `python -m pytest importer_EJEE/tests -q`. The sample includes configs for repeating the sequential `inspect`, `prepare`, `extract`, `figures`, `classify`, `pack`, `verify` phases. The default demo config uses the bundled Morin input fixture. Completed phases resume without repeating successful paid conversions.

The importer uses the containing PaperLab checkout when installed normally; a standalone deployment can use `reference/PaperLab` or `PAPERLAB_REPO`. All output isolation is set before importing upstream modules. Dependencies are pinned in the separate importer environment, leaving the main app's environment unchanged.

Question content contains only statements, equations, subparts, options and diagrams. Book titles, printed question labels and difficulty stars remain in provenance, not question text. Missing solutions are explicit; none are invented. Node 3 runs freshly, and a valid taxonomy-gap suggestion is preserved rather than forcing unrelated topics. Human source/crop review remains necessary; native save validation is not a full TeX compilation.

The sample's third-party textbook content retains its authors'/publishers' rights and is not represented as open-source textbook material. It is separated from importer code so maintainers can replace or remove it independently. Local virtual environments, generated runs and reference checkouts are gitignored.

Historical design/demo notes are in PLAN.md and DEMO_RESULTS.md; CHANGES.md describes the final behavior and takes precedence over earlier heading-preservation experiments. COST_ANALYSIS.md covers the original 18-question run; sample_data/manifest.json records the expanded sample's usage totals.
