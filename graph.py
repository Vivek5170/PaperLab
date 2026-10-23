"""LangGraph orchestration for the physics database pipeline.

Phase 1 (Indexer) is wired: START -> pre_check -> gate -> abort | indexer loop -> END.
Phase 2 (Extractor) plugs in later: indexer completion will route to the
extractor node instead of END. State already carries both phases' fields.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

import database
from llm import get_llm
from tools_indexer import (
    get_page_text,
    get_pdf_info,
    search_pdf_text,
    submit_metadata_and_boundaries,
)

PROMPTS_DIR = Path(__file__).parent / "prompts"

# Tools the Indexer LLM may call. get_pdf_info is deliberately EXCLUDED --
# the deterministic pre_check_node owns it, so a scanned PDF never reaches
# the agent.
INDEXER_TOOLS = [search_pdf_text, get_page_text, submit_metadata_and_boundaries]
_INDEXER_TOOLS_BY_NAME = {t.name: t for t in INDEXER_TOOLS}

SUBMIT_TOOL_NAME = "submit_metadata_and_boundaries"


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

    # LangGraph message state (for LLM memory)
    messages: List[BaseMessage]

    # Graph control & metrics
    status: str  # "running", "aborted_no_text", "indexer_complete"
    token_usage: dict
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
        "messages": [],
        "status": "running",
        "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
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


def _load_indexer_prompt(paper_id: int) -> str:
    text = (PROMPTS_DIR / "indexer_prompt.md").read_text(encoding="utf-8")
    return text.replace("{paper_id}", str(paper_id))


def _accumulate_usage(into: dict, msg: AIMessage) -> dict:
    usage = getattr(msg, "usage_metadata", None) or {}
    return {
        "prompt_tokens": into.get("prompt_tokens", 0) + usage.get("input_tokens", 0),
        "completion_tokens": into.get("completion_tokens", 0)
        + usage.get("output_tokens", 0),
        "total_tokens": into.get("total_tokens", 0) + usage.get("total_tokens", 0),
    }


def indexer_node(state: PipelineState) -> dict:
    """One ReAct turn: LLM step, then execute any requested tools.

    Returns updated messages (+ token totals). Sets status to
    "indexer_complete" only when the submit tool executed successfully.
    """
    llm = get_llm().bind_tools(INDEXER_TOOLS)
    messages: List[BaseMessage] = list(state.get("messages") or [])
    if not messages:
        if state.get("solution_pdf_path"):
            sol_line = (
                f"Solution PDF: {state['solution_pdf_path']} "
                f"({state['s_page_count']} pages, text layer present)"
            )
        else:
            sol_line = "Solution PDF: none provided"
        messages = [
            SystemMessage(content=_load_indexer_prompt(state["paper_id"])),
            HumanMessage(
                content=(
                    f"Question PDF: {state['question_pdf_path']} "
                    f"({state['q_page_count']} pages, text layer present)\n"
                    f"{sol_line}"
                )
            ),
        ]

    response = llm.invoke(messages)
    messages.append(response)
    token_usage = _accumulate_usage(state.get("token_usage") or {}, response)

    update: dict = {"messages": messages, "token_usage": token_usage}
    for call in getattr(response, "tool_calls", None) or []:
        tool = _INDEXER_TOOLS_BY_NAME.get(call["name"])
        if tool is None:
            messages.append(
                ToolMessage(
                    content=f"Error: unknown tool '{call['name']}'",
                    tool_call_id=call["id"],
                )
            )
            continue
        try:
            result = tool.invoke(call["args"])
            messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))
            if call["name"] == SUBMIT_TOOL_NAME:
                update["status"] = "indexer_complete"
        except Exception as exc:  # tool errors go back to the LLM, not up
            messages.append(
                ToolMessage(content=f"Error: {exc}", tool_call_id=call["id"])
            )
    return update


def route_indexer(state: PipelineState) -> str:
    """Loop while the agent is still working; finish once it submitted.

    "done" also covers the LLM stopping without tools (no infinite loop);
    status then stays "running" and the NULL-metadata row exposes the gap.
    """
    for msg in reversed(state.get("messages") or []):
        if isinstance(msg, AIMessage):
            names = [c["name"] for c in (msg.tool_calls or [])]
            if SUBMIT_TOOL_NAME in names:
                return "done"
            return "done" if not names else "continue"
    return "continue"


# --------------------------------------------------------------- graph ---


def build_graph():
    """Assemble the Phase 1 graph (Phase 2 attaches at the "done" edge)."""
    graph = StateGraph(PipelineState)
    graph.add_node("pre_check", pre_check_node)
    graph.add_node("abort", abort_node)
    graph.add_node("indexer", indexer_node)

    graph.add_edge(START, "pre_check")
    graph.add_conditional_edges(
        "pre_check", text_layer_gate, {"abort": "abort", "indexer": "indexer"}
    )
    graph.add_edge("abort", END)
    graph.add_conditional_edges(
        "indexer", route_indexer, {"continue": "indexer", "done": END}
    )
    return graph.compile()


app = build_graph()
