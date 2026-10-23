"""Background run registry: pipeline runs as pool jobs, polled across reruns.

Lives in an imported module (NOT app.py) so the pool and futures survive
Streamlit script reruns via the import cache. No streamlit import here --
headless-testable. Callables run in worker threads and must never touch
``st`` (``run_pipeline`` is pure backend, so it qualifies).
"""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable


class RunRegistry:
    """Submit callables by key; poll running/completed across reruns.

    Contract: a job returns one ``(pid, status, info)`` row; a batch job
    returns a list of such rows. A raising job surfaces as ``(key, "error",
    "ExcType: msg")``.
    """

    def __init__(self, max_workers: int = 3) -> None:
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="paperlab-run"
        )
        self._futures: dict[Any, Future] = {}

    def submit(self, key: Any, fn: Callable, *args: Any) -> bool:
        """Submit ``fn(*args)`` unless key already has a live job."""
        pending = self._futures.get(key)
        if pending is not None and not pending.done():
            return False
        self._futures[key] = self._pool.submit(fn, *args)
        return True

    def running(self) -> list[Any]:
        """Keys with unfinished jobs."""
        return sorted(
            (k for k, f in self._futures.items() if not f.done()), key=repr
        )

    def completed(self) -> list[tuple[Any, str, str]]:
        """One ``(pid-or-key, status, info)`` row per finished job."""
        out: list[tuple[Any, str, str]] = []
        for key, fut in self._futures.items():
            if not fut.done():
                continue
            try:
                res = fut.result()
            except Exception as exc:  # noqa: BLE001 -- surfaced in the UI
                out.append((key, "error", f"{type(exc).__name__}: {exc}"))
                continue
            out.extend(res if isinstance(res, list) else [res])
        return out

    def clear_finished(self) -> int:
        """Drop finished jobs; return how many were dropped."""
        done = [k for k, f in self._futures.items() if f.done()]
        for k in done:
            del self._futures[k]
        return len(done)


_REGISTRY: RunRegistry | None = None
_BOOT_RESET_DONE = False


def get_registry() -> RunRegistry:
    """Process-wide singleton: one pool, one job map, all sessions."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = RunRegistry()
    return _REGISTRY


def reset_stuck_running_once() -> list[int]:
    """Fail papers left mid-flight by a dead server restart. Once per process.

    Background threads die with the server, so a running status surviving a
    fresh boot can never complete. (A CLI run in another terminal self-heals:
    it overwrites the status when it finishes.)
    """
    global _BOOT_RESET_DONE
    if _BOOT_RESET_DONE:
        return []
    _BOOT_RESET_DONE = True
    import database

    return database.reset_stuck_running()
