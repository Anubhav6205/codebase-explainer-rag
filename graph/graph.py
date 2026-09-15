from langgraph.graph import END, START, StateGraph
import sys,os

from agents.citation_check import citation_check_agent
from agents.decompose import decompose_agent
from agents.human_verify import human_verify_agent
from agents.searcher import searcher_agent
sys.path.insert(0,os.path.join(os.path.dirname(__file__),'..'))
from agents.coverage_check import coverage_check_agent
from agents.response import response_agent
from state import MessageState
from langgraph.checkpoint.memory import InMemorySaver

MAX_HOPS = 3
MAX_CITATION_RETRIES = 2


# --- Route functions ---


def route_coverage_check(state: MessageState) -> str:
    if state.get("is_sufficient"):
        return "response"
    if state.get("hop_count", 0) >= MAX_HOPS:
        return "response"  # response handles abstention when hops exhausted
    return "decompose"


def route_citation_check(state: MessageState) -> str:
    if state.get("citation_passed"):
        return "human_verify"
    if state.get("citation_retry_count", 0) >= MAX_CITATION_RETRIES:
        return "human_verify"
    return "response"


def route_human_verify(state: MessageState) -> str:
    decision = state.get("human_decision")
    if decision == "reject_with_feedback":
        return "decompose"
    return END  # approve OR reject_no_feedback → terminal


# --- Graph wiring ---

g = StateGraph(MessageState)

g.add_node("decompose", decompose_agent)
g.add_node("searcher", searcher_agent)
g.add_node("coverage_check", coverage_check_agent)
g.add_node("response", response_agent)
g.add_node("citation_check", citation_check_agent)
g.add_node("human_verify", human_verify_agent)

g.add_edge(START, "decompose")
g.add_edge("decompose", "searcher")
g.add_edge("searcher", "coverage_check")
g.add_edge("response", "citation_check")

g.add_conditional_edges(
    "coverage_check",
    route_coverage_check,
    {"response": "response", "decompose": "decompose"},
)

g.add_conditional_edges(
    "citation_check",
    route_citation_check,
    {"human_verify": "human_verify", "response": "response"},
)

g.add_conditional_edges(
    "human_verify",
    route_human_verify,
    {"decompose": "decompose", END: END},
)
checkpointer = InMemorySaver()
app = g.compile(checkpointer=checkpointer)
