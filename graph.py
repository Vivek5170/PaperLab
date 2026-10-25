"""LangGraph orchestration for the physics database pipeline.

Phase 1 (Indexer): START -> pre_check -> gate -> abort | indexer loop.
Phase 2 (Extractor): clean (PDFs) -> extractor_init (boundaries) -> loop.

Three compiled entry points share the same nodes:
- ``phase1_app``: Phase 1 only (used by run_indexer.py).
- ``extractor_app``: Phase 2 only, from ``clean`` (used by
  run_extractor.py with ``{"paper_id": ..., "messages": []}``).
- ``app``: full pipeline, indexer completion routes into clean.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from typing_extensions import TypedDict

import database
from llm import get_llm, invoke_with_retry
from tools_extractor import (
    assisted_crop,
    get_page_image,
    exact_crop,
    submit_question,
    submit_solution,
    verify_latex_syntax,
)
from tools_indexer import (
    get_page_text,
    get_pdf_info,
    search_pdf_text,
    submit_metadata_and_boundaries,
)

PROMPTS_DIR = Path(__file__).parent / "prompts"

# Tools per agent. get_pdf_info is deliberately EXCLUDED from both --
# the deterministic pre_check_node owns it, so a scanned PDF never reaches
# an agent. verify_latex_syntax is NOT bound either -- the merged submit
# tools compile-check internally and return NOT SAVED on errors.
INDEXER_TOOLS = [search_pdf_text, get_page_text, submit_metadata_and_boundaries]
EXTRACTOR_TOOLS = [
    get_page_image,
    assisted_crop,
    exact_crop,
    submit_question,
    submit_solution,
    get_page_text,  # key-sheet reads
]

# Tools whose results arrive as a Command (text ToolMessage + image
# HumanMessage). They need the LangChain tool_call_id injected at invoke.
COMMAND_TOOLS = {get_page_image.name, assisted_crop.name, exact_crop.name}

INDEXER_SUBMIT_TOOL = "submit_metadata_and_boundaries"


class PipelineState(TypedDict):
    paper_id: int
    question_pdf_path: str
    solution_pdf_path: Optional[str]

    # Pre-check flags
    q_has_text: bool
    s_has_text: bool

    # Pre-check facts (probed deterministically; handed to the agent so it
    # never needs to discover them with tool calls)
    q_page_count: int
    s_page_count: Optional[int]

    # Phase 2 boundaries (populated by extractor_init_node from the DB)
    q_start: Optional[int]
    q_end: Optional[int]
    s_start: Optional[int]
    s_end: Optional[int]

    # LangGraph message state (for LLM memory)
    messages: List[BaseMessage]

    # Graph control & metrics
    status: str  # "running", "aborted_no_text", "indexer_complete", "extractor_complete"
    execution_time_sec: float


def initial_state(
    paper_id: int, question_pdf_path: str, solution_pdf_path: Optional[str] = None
) -> PipelineState:
    """Build the starting state (also the LangGraph state contract)."""
    return {
        "paper_id": paper_id,
        "question_pdf_path": question_pdf_path,
        "solution_pdf_path": solution_pdf_path,
        "q_has_text": False,
        "s_has_text": False,
        "q_page_count": 0,
        "s_page_count": None,
        "q_start": None,
        "q_end": None,
        "s_start": None,
        "s_end": None,
        "messages": [],
        "status": "running",
        "execution_time_sec": 0.0,
    }


# ---------------------------------------------------------------- nodes ---


def pre_check_node(state: PipelineState) -> dict:
    """Deterministic gate input: probe text layers, no LLM involved."""
    q_info = get_pdf_info.invoke({"pdf_path": state["question_pdf_path"]})
    update: dict = {
        "q_has_text": bool(q_info["has_text_layer"]),
        "q_page_count": int(q_info["page_count"]),
        "s_has_text": False,
        "s_page_count": None,
    }
    if state.get("solution_pdf_path"):
        s_info = get_pdf_info.invoke({"pdf_path": state["solution_pdf_path"]})
        update["s_has_text"] = bool(s_info["has_text_layer"])
        update["s_page_count"] = int(s_info["page_count"])
    return update


def text_layer_gate(state: PipelineState) -> str:
    """Route on the question PDF's text layer (solutions may be absent)."""
    return "abort" if not state["q_has_text"] else "indexer"


def abort_node(state: PipelineState) -> dict:
    """Terminal path: archive the stub row, record the abort, stop."""
    database.mark_paper_archived(state["paper_id"])
    return {"status": "aborted_no_text"}


def _load_indexer_prompt() -> str:
    return (PROMPTS_DIR / "indexer_prompt.md").read_text(encoding="utf-8")


def _load_extractor_prompt() -> str:
    return (PROMPTS_DIR / "extractor_prompt.md").read_text(encoding="utf-8")


def _run_agent_turn(
    state: PipelineState,
    tools: list,
    opener: Callable[[], List[BaseMessage]],
    submit_names: set,
    done_status: Optional[str],
    phase: str,
) -> dict:
    """One ReAct turn: LLM step, then execute any requested tools.

    ``submit_names``: tool names whose success sets ``done_status``.
    If ``done_status`` is None, completion is decided by routing only.
    Every AI message's usage is appended to the token_usage table.

    Ordering: parallel tool calls are disabled so each image-bearing result
    lands immediately after its own tool call, keeping history append-only.
    """
    llm = get_llm().bind_tools(tools, parallel_tool_calls=False)
    by_name = {t.name: t for t in tools}
    messages: List[BaseMessage] = list(state.get("messages") or [])
    if not messages:
        messages = opener()

    response = invoke_with_retry(llm, messages)
    messages.append(response)
    usage = getattr(response, "usage_metadata", None) or {}
    in_det = usage.get("input_token_details", None) or {}
    out_det = usage.get("output_token_details", None) or {}
    database.log_token_usage(
        state["paper_id"],
        phase,
        input_tokens=usage.get("input_tokens", 0),
        cache_read=in_det.get("cache_read", 0),
        output_tokens=usage.get("output_tokens", 0),
        reasoning_tokens=out_det.get("reasoning", 0),
    )

    update: dict = {"messages": messages}
    for call in getattr(response, "tool_calls", None) or []:
        tool = by_name.get(call["name"])
        if tool is None:
            messages.append(
                ToolMessage(
                    content=f"Error: unknown tool '{call['name']}",
                    tool_call_id=call["id"],
                )
            )
            continue
        try:
            if call["name"] in COMMAND_TOOLS:
                # InjectedToolCallId tools need the full model ToolCall shape.
                result = tool.invoke(
                    {
                        "name": call["name"],
                        "args": dict(call["args"]),
                        "id": call["id"],
                        "type": "tool_call",
                    }
                )
            else:
                result = tool.invoke(call["args"])
            if isinstance(result, Command):
                # Image-bearing result: text ToolMessage + image HumanMessage.
                messages.extend(result.update.get("messages", []))
            else:
                messages.append(
                    ToolMessage(content=str(result), tool_call_id=call["id"])
                )
            if call["name"] in submit_names and done_status is not None:
                update["status"] = done_status
        except Exception as exc:  # tool errors go back to the LLM, not up
            messages.append(
                ToolMessage(content=f"Error: {exc}", tool_call_id=call["id"])
            )
    return update


def indexer_node(state: PipelineState) -> dict:
    """One Indexer ReAct turn; sets "indexer_complete" on submit success."""
    if state.get("solution_pdf_path"):
        sol_line = (
            f"Solution PDF: {state['solution_pdf_path']} "
            f"({state['s_page_count']} pages, text layer present)"
        )
    else:
        sol_line = "Solution PDF: none provided"
    opener = lambda: [  # noqa: E731
        SystemMessage(content=_load_indexer_prompt()),
        HumanMessage(
            content=(
                f"paper_id: {state['paper_id']}\n"
                f"Question PDF: {state['question_pdf_path']} "
                f"({state['q_page_count']} pages, text layer present)\n"
                f"{sol_line}"
            )
        ),
    ]
    return _run_agent_turn(
        state, INDEXER_TOOLS, opener, {INDEXER_SUBMIT_TOOL}, "indexer_complete",
        phase="indexer",
    )


def route_indexer(state: PipelineState) -> str:
    """Loop while the agent is still working; finish once it submitted.

    "done" also covers the LLM stopping without tools (no infinite loop);
    status then stays "running" and the NULL-metadata row exposes the gap.
    """
    for msg in reversed(state.get("messages") or []):
        if isinstance(msg, AIMessage):
            names = [c["name"] for c in (msg.tool_calls or [])]
            if INDEXER_SUBMIT_TOOL in names:
                return "done"
            return "done" if not names else "continue"
    return "continue"


def clean_node(state: PipelineState) -> dict:
    """Deterministic cleaning step: the extractor sees ONLY cleaned PDFs.

    Runs between Phase 1 and Phase 2 in every graph. Fail-open inside --
    on any error the original paths are kept, so extraction still runs.
    clean_paper_pdfs also pre-builds the figure-only crop canvases
    ({tag}_q/s_crop.pdf: chrome removed + long text truly deleted);
    crop tools resolve to them automatically, transcription keeps the
    full cleaned pages.
    """
    from pdf_clean import clean_paper_pdfs

    cleaned = clean_paper_pdfs(state["paper_id"])
    return {
        "question_pdf_path": cleaned["question_pdf"],
        "solution_pdf_path": cleaned["solution_pdf"],
    }


def postprocess_node(state: PipelineState) -> dict:
    """Once-per-paper figure cleanup after extraction completes.

    Border peepings + loose whitespace on every saved figure, no AI.
    Idempotent (re-runs are no-ops) and fail-open: never fails the
    pipeline, never touches state.
    """
    try:
        from postprocess_figures import postprocess_paper
        rep = postprocess_paper(state["paper_id"])
        peeps = sum(r.get("peeps_removed", 0) for r in rep.values())
        trims = sum(1 for r in rep.values() if r.get("trimmed"))
        print(f"postprocess: paper {state['paper_id']}: {len(rep)} "
              f"figures, {peeps} peepings removed, {trims} trimmed")
    except Exception as exc:
        print(f"postprocess: paper {state['paper_id']} skipped "
              f"({type(exc).__name__}: {exc})")
    return {}


def _existing_id_scheme(paper_id: int) -> str | None:
    """Naming convention already stored for this paper, if any.

    Returns "namespaced" (A-01...), "bare" (1, 2...), "mixed", or None
    when no questions exist yet. Reruns/resumes lock onto whatever the
    first run chose, so one paper never mixes styles across runs.
    """
    import re

    conn = database.get_connection()
    try:
        rows = conn.execute(
            "SELECT question_number FROM questions WHERE paper_id = ?",
            (paper_id,),
        ).fetchall()
    finally:
        conn.close()
    names = [r[0] for r in rows]
    if not names:
        return None
    ns = [n for n in names if re.match(r"^[A-Za-z]+-\d+", n or "")]
    if len(ns) == len(names):
        return "namespaced"
    if not ns:
        return "bare"
    return "mixed"


def extractor_init_node(state: PipelineState) -> dict:
    """Deterministic Phase 2 entry: load boundaries + paths from the DB.

    Aborted/never-indexed papers have NULL boundaries: route them out with
    "aborted_no_text" instead of waking the vision agent for nothing.
    PDF paths set by clean_node (cleaned copies) are respected; the DB
    originals are only a fallback for states that skipped cleaning.
    """
    row = database.get_paper(state["paper_id"])
    if row is None:
        raise ValueError(f"paper_id {state['paper_id']} does not exist")
    if row["q_start"] is None or row["q_end"] is None:
        return {"status": "aborted_no_text"}
    update = {
        "q_start": row["q_start"],
        "q_end": row["q_end"],
        "s_start": row["s_start"],
        "s_end": row["s_end"],
    }
    if not state.get("question_pdf_path"):
        update["question_pdf_path"] = row["question_pdf_path"]
    if not state.get("solution_pdf_path"):
        update["solution_pdf_path"] = row["solution_pdf_path"]
    return update


def route_extractor_init(state: PipelineState) -> str:
    """Skip the vision agent for papers with nothing to extract."""
    return "end" if state.get("status") == "aborted_no_text" else "extractor"


def extractor_node(state: PipelineState) -> dict:
    """One Extractor ReAct turn (vision-heavy); stopping means finished."""
    q_range = f"pages {state.get('q_start')}-{state.get('q_end')}"
    if state.get("s_start") is not None and state.get("s_end") is not None:
        s_range = f"pages {state['s_start']}-{state['s_end']}"
    else:
        s_range = "none provided"
    if state.get("solution_pdf_path"):
        sol_line = f"Solution PDF: {state['solution_pdf_path']} (solutions {s_range})"
    else:
        sol_line = "Solution PDF: none provided"
    scheme = _existing_id_scheme(state["paper_id"])
    scheme_line = (
        f"\nID scheme for this paper: {scheme} (existing questions "
        "already use it -- continue identically, never mix styles)."
        if scheme in ("bare", "namespaced") else ""
    )
    opener = lambda: [  # noqa: E731
        SystemMessage(content=_load_extractor_prompt()),
        HumanMessage(
            content=(
                f"paper_id: {state['paper_id']}\n"
                f"Question PDF: {state['question_pdf_path']} "
                f"(physics questions {q_range})\n"
                f"{sol_line}\n"
                "These are cleaned copies (watermarks removed); pagination "
                "and geometry are identical to the originals. "
                "Crop tools (assisted_crop/exact_crop) automatically see "
                "a figure-only canvas of these PDFs (long question text "
                "deleted, diagram ink intact) -- pass the paths as given."
                f"{scheme_line}"
            )
        ),
    ]
    update = _run_agent_turn(state, EXTRACTOR_TOOLS, opener, set(), None,
                               phase="extractor")
    # Per the extractor prompt, the agent stops only when every physics
    # question + solution in range is submitted -- so an idle turn marks
    # completion. (Verify via Outputs/ + questions rows, not this flag.)
    last_ai: Optional[AIMessage] = None
    for msg in reversed(update["messages"]):
        if isinstance(msg, AIMessage):
            last_ai = msg
            break
    if last_ai is not None and not (last_ai.tool_calls or []):
        update["status"] = "extractor_complete"
    return update


def route_extractor(state: PipelineState) -> str:
    """Standard tool loop: tool calls present -> back to the agent."""
    for msg in reversed(state.get("messages") or []):
        if isinstance(msg, AIMessage):
            return "continue" if (msg.tool_calls or []) else "done"
    return "continue"


# --------------------------------------------------------------- graphs ---


def _add_phase1(graph: StateGraph, indexer_done_target: str = "clean") -> None:
    graph.add_node("pre_check", pre_check_node)
    graph.add_node("abort", abort_node)
    graph.add_node("indexer", indexer_node)
    graph.add_edge(START, "pre_check")
    graph.add_conditional_edges(
        "pre_check", text_layer_gate, {"abort": "abort", "indexer": "indexer"}
    )
    graph.add_edge("abort", END)
    graph.add_conditional_edges(
        "indexer", route_indexer, {"continue": "indexer", "done": indexer_done_target}
    )


def _add_extractor(graph: StateGraph, entry: Optional[str]) -> None:
    graph.add_node("clean", clean_node)
    graph.add_node("extractor_init", extractor_init_node)
    graph.add_node("extractor", extractor_node)
    graph.add_node("postprocess", postprocess_node)
    if entry is not None:
        # Standalone extractor graph: START enters here. In the full
        # graph Phase 1 routes into "clean" directly (indexer_done_target).
        graph.add_edge(entry, "clean")
    graph.add_edge("clean", "extractor_init")
    graph.add_conditional_edges(
        "extractor_init",
        route_extractor_init,
        {"end": END, "extractor": "extractor"}
    )
    graph.add_conditional_edges(
        "extractor", route_extractor,
        {"continue": "extractor", "done": "postprocess"}
    )
    graph.add_edge("postprocess", END)


def build_phase1_graph():
    """Phase 1 only: indexer completion routes to END."""
    graph = StateGraph(PipelineState)
    _add_phase1(graph, END)
    return graph.compile()


def build_extractor_graph():
    """Phase 2 only: START -> clean -> extractor_init (Phase 1 bypassed)."""
    graph = StateGraph(PipelineState)
    _add_extractor(graph, START)
    return graph.compile()


def build_graph():
    """Full pipeline: indexer completion routes into clean, then Phase 2."""
    graph = StateGraph(PipelineState)
    _add_phase1(graph)
    _add_extractor(graph, None)
    return graph.compile()


phase1_app = build_phase1_graph()
extractor_app = build_extractor_graph()
app = build_graph()
