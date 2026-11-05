"""PaperLab REST backend: thin HTTP layer over the existing pipeline code.

Every domain operation reuses the tested modules next to it (database,
directory_manager, pairing, render, runs, run_pipeline, config). This package
adds no extraction logic of its own.
"""
