"""Run the unchanged upstream API against an isolated import run."""
import argparse
from pathlib import Path
from bootstrap import ROOT, activate

p = argparse.ArgumentParser()
p.add_argument('--run-dir', default='runs/morin-chapter-01')
p.add_argument('--port', type=int, default=8011)
args = p.parse_args()
activate(ROOT / args.run_dir)
import uvicorn
uvicorn.run('backend.main:app', host='127.0.0.1', port=args.port)
