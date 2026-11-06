"""PaperLab API: FastAPI app wiring the routers to the existing code."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import config  # noqa: F401  (pins env first, same as every entry point)
import database
from app.pairing import reconcile_missing_sources
from app.runs import reset_stuck_running_once
from backend.routers import auth, figures, inbox, jobs, papers, search, stats, tex, topics, uploads

app = FastAPI(title="PaperLab API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    database.init_db()
    reset_stuck_running_once()
    reconcile_missing_sources()


@app.get("/api/health")
def health():
    return {"ok": True}


app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
# Figures BEFORE papers: its static GET /trash must win over the papers
# router's file-serving GET figures/{name}.
app.include_router(figures.router, prefix="/api/papers/{paper_id}/questions/{qn}/figures",
                   tags=["figures"])
app.include_router(papers.router, prefix="/api/papers", tags=["papers"])
app.include_router(tex.router, prefix="/api/papers", tags=["tex"])
app.include_router(inbox.router, prefix="/api/inbox", tags=["inbox"])
app.include_router(topics.router, prefix="/api/topics", tags=["topics"])
app.include_router(search.router, prefix="/api/search", tags=["search"])
app.include_router(figures.router, prefix="/api/papers/{paper_id}/questions/{qn}/figures",
                   tags=["figures"])
app.include_router(stats.router, prefix="/api/stats", tags=["stats"])
app.include_router(uploads.router, prefix="/api/uploads", tags=["uploads"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])

_FRONTEND_BUILD = Path(__file__).parent.parent / "frontend" / "build"
if _FRONTEND_BUILD.is_dir():
    # Production: serve the Svelte static build; /api routes take precedence.
    app.mount("/", StaticFiles(directory=_FRONTEND_BUILD, html=True), name="site")
