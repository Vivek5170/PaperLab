"""Background jobs: thin view over app/runs.py RunRegistry (admin)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.runs import get_registry
from backend.deps import require_admin
from run_pipeline import run_pipeline

router = APIRouter()


def _run(pid: int, force: bool):
    try:
        out = run_pipeline(pid, force=force)
        return pid, out["status"], out["elapsed_sec"]
    except Exception as exc:  # noqa: BLE001 -- surfaced per paper
        return pid, "error", str(exc)


def _run_sequential(pids: list[int], force: bool):
    return [_run(pid, force) for pid in pids]


@router.get("", dependencies=[Depends(require_admin)])
def list_jobs():
    reg = get_registry()
    running = [
        {"key": str(k), "status": "running"} for k in reg.running()
    ]
    finished = [
        {"key": str(pid), "status": st, "info": info}
        for pid, st, info in reg.completed()
    ]
    return {"running": running, "finished": finished}


class RunBody(BaseModel):
    ids: list[int]
    mode: str = "sequential"
    force: bool = False


@router.post("", dependencies=[Depends(require_admin)])
def submit_jobs(body: RunBody):
    reg = get_registry()
    started = []
    if body.mode == "sequential":
        if reg.submit(("batch", tuple(body.ids)), _run_sequential, body.ids, body.force):
            started.append(f"batch of {len(body.ids)}")
    else:
        for pid in body.ids:
            if reg.submit(pid, _run, pid, body.force):
                started.append(f"#{pid}")
    return {"started": started}
