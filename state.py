import operator

from langchain_core.messages import AnyMessage
from typing_extensions import TypedDict, Annotated


class Chunk(TypedDict):
    id: str | int              # Qdrant point id — the citation handle
    text: str                  # the actual chunk content
    score: float               # rerank score
    source_file: str | None    # file path — for citation display
    headers: str | None        # docs only: joined "H1 > H2 > H3"
    query: str                 # which decompose query surfaced this


class MessageState(TypedDict):
    """State for the agents. Fields grouped by owner (whichever node writes them)."""

    # --- Input (set once at graph start) ---
    question: str

    # --- Loop control (owned by graph routing / searcher) ---
    hop_count: int

    # --- decompose ---
    current_decompose_queries: list[str]                          # queries for this hop
    total_decompose_queries: Annotated[list[str], operator.add]   # accumulated across hops (never repeat)
    checklist: list[str]                                            # items that must be covered (hop 2+)

    # --- searcher ---
    retrieved_chunks: Annotated[list[Chunk], operator.add]          # accumulated across hops
    chunks_added_this_hop: int                                      # count of NEW chunks this hop (for no-progress detection)

    # --- coverage_check ---
    coverage_map: dict[str, list[str]]                              # checklist item -> chunk_ids covering it
    is_sufficient: bool

    # --- response ---
    answer: str
    citations: list[dict]                                           # [{"claim": str, "chunk_ids": list[str]}]

    # --- citation_check ---
    citation_passed: bool
    citation_retry_count: int

    # --- HITL ---
    human_decision: str                                             # "approve" | "reject_no_feedback" | "reject_with_feedback"
    human_feedback: str                                             # cleared by decompose after use
    human_retry_count: int                                          # bumped on reject_with_feedback

    # --- Termination bookkeeping (set by whichever node ends the run) ---
    termination_reason: str                                         # "approved" | "exhausted" | "citation_verification_failed" | "rejected_no_feedback"
