from phoenix.otel import register

tracer_provider = register(
  project_name="CAPSTONE",
  auto_instrument=True,
    endpoint="http://localhost:6006/v1/traces",
    verbose=False
)




from langgraph.graph import END, START, StateGraph
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from agents.citation_check import citation_check_agent
from agents.decompose import decompose_agent
from agents.human_verify import human_verify_agent
from agents.searcher import searcher_agent


from agents.coverage_check import coverage_check_agent
from agents.response import response_agent
from state import MessageState
from langgraph.checkpoint.memory import InMemorySaver

MAX_HOPS = 3
MAX_CITATION_RETRIES = 2
MAX_HUMAN_RETRIES = 2

# --- Route functions ---


def route_coverage_check(state: MessageState) -> str:
    hop = state.get("hop_count", 0)
    is_sufficient = state.get("is_sufficient", False)
    added = state.get("chunks_added_this_hop", 0)
    print(f"[route_coverage_check] hop={hop} is_sufficient={is_sufficient} chunks_added_this_hop={added}")

    if state.get("is_sufficient"):
        print(f"[route_coverage_check] -> response (is_sufficient=True)")
        return "response"
    if state.get("hop_count", 0) >= MAX_HOPS:
        print(f"[route_coverage_check] -> response (hop_cap hit, MAX_HOPS={MAX_HOPS})")
        return "response"  # response handles abstention when hops exhausted
    # No-progress detection: after hop 1 grounding, if a hop returned zero new
    # chunks, another hop won't help — abstain instead of burning tokens.
    if state.get("hop_count", 0) > 1 and state.get("chunks_added_this_hop", 0) == 0:
        print(f"[route_coverage_check] -> response (no-progress)")
        return "response"
    print(f"[route_coverage_check] -> decompose (retry)")
    return "decompose"


def route_citation_check(state: MessageState) -> str:
    passed = state.get("citation_passed", False)
    retries = state.get("citation_retry_count", 0)
    print(f"[route_citation_check] citation_passed={passed} citation_retry_count={retries}")

    if state.get("citation_passed"):
        print(f"[route_citation_check] -> human_verify (passed)")
        return "human_verify"
    if state.get("citation_retry_count", 0) >= MAX_CITATION_RETRIES:
        print(f"[route_citation_check] -> human_verify (retry_cap hit, MAX={MAX_CITATION_RETRIES})")
        return "human_verify"
    print(f"[route_citation_check] -> response (retry)")
    return "response"


def route_human_verify(state: MessageState) -> str:
    decision = state.get("human_decision")
    human_retries = state.get("human_retry_count", 0)
    print(f"[route_human_verify] human_decision={decision!r} human_retry_count={human_retries}")

    if decision == "reject_with_feedback":
        if state.get("human_retry_count", 0) >= MAX_HUMAN_RETRIES:
            print(f"[route_human_verify] -> END (human_retry_cap hit, MAX={MAX_HUMAN_RETRIES})")
            return END
        print(f"[route_human_verify] -> decompose (feedback loop)")
        return "decompose"
    final_answer = state.get("answer", "")
    termination_reason = state.get("termination_reason", "")
    print(f"[route_human_verify] FINAL answer(len={len(final_answer)}) termination_reason={termination_reason!r}")
    print(f"[route_human_verify] -> END (terminal: {decision})")
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
print(f"[graph] compiled with MAX_HOPS={MAX_HOPS} MAX_CITATION_RETRIES={MAX_CITATION_RETRIES} MAX_HUMAN_RETRIES={MAX_HUMAN_RETRIES}")
