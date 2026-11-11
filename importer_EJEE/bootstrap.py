"""Bind upstream PaperLab to an isolated store BEFORE importing its modules."""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parent
REPO = Path(os.environ.get('PAPERLAB_REPO', ROOT / 'reference' / 'PaperLab')).resolve()
if not REPO.is_dir() and (ROOT.parent / 'database.py').is_file():
    REPO = ROOT.parent


def activate(run_dir):
    run = Path(run_dir).resolve()
    if ROOT not in run.parents or run == REPO or ROOT / 'reference' in run.parents or (REPO != ROOT.parent and REPO in run.parents):
        raise ValueError('Run directory must be inside importer_EJEE, outside reference/')
    run.mkdir(parents=True, exist_ok=True)
    from dotenv import dotenv_values
    # The existing Meta credential is reused in memory, never copied or logged.
    settings = dotenv_values(ROOT.parent / '.env')
    if not os.environ.get('META_API_KEY') and settings.get('META_API_KEY'):
        os.environ['META_API_KEY'] = settings['META_API_KEY']
    os.environ['PHYSICS_ARCHIVE_DB'] = str(run / 'paperlab.db')
    os.environ['PHYSICS_OUTPUT_BASE'] = str(run / 'Outputs')
    os.environ['DATA_ROOT'] = str(run / 'data')
    os.environ['PIPELINE_CONFIG'] = str(REPO / 'config.yaml')
    os.environ['LANGCHAIN_TRACING_V2'] = 'false'
    os.environ['LANGSMITH_TRACING'] = 'false'
    sys.path.insert(0, str(REPO))
    return run
