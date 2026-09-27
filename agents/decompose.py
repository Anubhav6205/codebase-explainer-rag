from langchain.messages import AIMessage, HumanMessage, SystemMessage
from langchain.chat_models import init_chat_model
from pydantic import BaseModel, Field

import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from state import MessageState


class DecomposeOutput(BaseModel):
    queries: list[str] = Field(
        description="Holds all the queries to be fetched from database based on user question"
    )
    checklist: list[str] = Field(
        description="Holds the list of questions that must be answered to consider the original query as answered"
    )


decompose_model = init_chat_model("gpt-4.1-mini").with_structured_output(DecomposeOutput)


DECOMPOSE_DOMAIN_TERM_SYS = SystemMessage(content="""\
You are the grounding step of a codebase Q&A agent. This is HOP 1.

Your only job: read the user's question and extract every domain-specific term a
new developer would need to look up in the target repository before the question
can be decomposed. These are the terms whose meaning is not obvious from general
knowledge.

Include:
- Identifiers, class names, function names, constants (verbatim, exact casing)
- Config keys and config filenames (e.g. `catalog-info.yaml`, `DEFAULT_NAMESPACE`)
- Domain-specific nouns even if they are natural-language phrases (e.g. "reverse relation")

Exclude:
- Generic English words ("string", "field", "system", "how", "work")
- Standard library / language primitives ("array", "boolean")
- Terms whose meaning is obvious without repo context

For each extracted term, emit ONE lookup query. Format each query as a short
noun phrase suitable for hybrid search — not a full sentence, not a question.
Prefer the verbatim identifier over paraphrases so BM25 matches exactly.

Return only the `queries` field. Do not decompose the question into sub-questions —
that comes in later hops. Grounding first, decomposition second.
""")


DECOMPOSE_USER_QUERY_SYS = SystemMessage(content="""\
You are the decomposition step of a codebase Q&A agent. This is HOP 2 OR LATER.

Grounding is done. You now have:
- The original question
- The chunks retrieved so far
- The queries already tried in prior hops
- (Optionally) coverage gaps flagged by the previous coverage_check pass
- (Optionally) human feedback from a HITL rejection

You must produce TWO things:

--------------------------------------------------------------------------
1. `checklist` — the ANSWER PLAN
--------------------------------------------------------------------------
An enumerated list of sub-questions that MUST all be answered for the original
question to be considered complete. Each item is a full natural-language
sub-question, not a search string.

Rules for the checklist:
- Each item stands alone and can be judged individually as answered or not
- Cover ALL facets the original question touches — behaviour, location, wiring,
  validation, failure paths — whichever apply
- For relational questions ("how does X associate to Y"), use this fixed
  6-point template:
    (a) what X is,
    (b) what Y is,
    (c) where they touch,
    (d) direction and cardinality of the link,
    (e) where the link is enforced,
    (f) what happens when the link is violated
- On hop 2 you AUTHOR the checklist. On hop 3+ INHERIT the previous checklist
  verbatim (do not rewrite it) unless HITL feedback demands new items — the
  checklist is stable across hops so coverage tracking makes sense
- 3–8 items typical; more only if the question genuinely needs it

--------------------------------------------------------------------------
2. `queries` — the SEARCH PLAN
--------------------------------------------------------------------------
Short noun phrases / identifiers you want the retriever to search for THIS hop.
Targeted at uncovered checklist items.

Rules for queries:
- One item in the checklist may need several queries; one query may serve
  several items — checklist and queries are NOT 1-to-1
- If a checklist item is uncovered, emit queries that approach it from a
  DIFFERENT angle than what was tried before (rephrase, target a related
  identifier, look in the other corpus)
- If human_feedback is present, fold it in as an explicit search target
- Prefer verbatim identifiers and exact tokens over paraphrases — hybrid search
  rewards BM25 hits on exact symbols
- NEVER re-query anything already in the prior queries list

Return only the `checklist` and `queries` fields. Do not synthesise an answer,
do not narrate your reasoning — the coverage_check step will judge sufficiency
arithmetically against the checklist you produce here.
""")


def decompose_agent(state: MessageState):
    is_grounding_hop = state.get("hop_count", 0) == 0
    hop_count_in = state.get("hop_count", 0)
    print(f"[decompose] ENTER hop={hop_count_in} is_grounding={is_grounding_hop}")

    sys_prompt = (
        DECOMPOSE_DOMAIN_TERM_SYS if is_grounding_hop else DECOMPOSE_USER_QUERY_SYS
    )

    user_question = state.get("question", "")

    if is_grounding_hop:
        message = HumanMessage(content=f"Question: {user_question}")
        print(
            f"[decompose] transform question(str) -> HumanMessage | before: {user_question[:80]!r}... | after: HumanMessage(<{len(user_question)} chars>)"
        )
    else:
        raw_chunks = state.get("retrieved_chunks", [])
        retrieved_chunks_str = (
            "\n\n".join(
                f"[id={chunk['id']}] file={chunk.get('source_file') or chunk.get('headers') or '?'} | for-query={chunk['query']}\n{chunk['text'][:400]}"
                for chunk in state.get("retrieved_chunks", [])
            )
            or "(none)"
        )
        print(
            f"[decompose] transform retrieved_chunks(list) -> str | before: list(len={len(raw_chunks)}) | after: str(len={len(retrieved_chunks_str)})"
        )

        raw_queries = state.get("total_decompose_queries", [])
        prior_queries_str = (
            "\n".join(f"- {q}" for q in state.get("total_decompose_queries", []))
            or "(none)"
        )
        print(
            f"[decompose] transform total_decompose_queries(list) -> str | before: {raw_queries[:2]}... (total={len(raw_queries)}) | after: str(len={len(prior_queries_str)})"
        )

        coverage_map = state.get("coverage_map", {}) or {}
        uncovered = [item for item, covering in coverage_map.items() if not covering]
        uncovered_str = "\n".join(f"- {item}" for item in uncovered) or "(none)"
        print(
            f"[decompose] transform coverage_map(dict) -> uncovered(list) | before: keys={list(coverage_map.keys())[:2]}... | after: uncovered={uncovered[:2]}... (count={len(uncovered)})"
        )

        human_feedback = state.get("human_feedback", "") or "(none)"

        context = (
            f"Question: {user_question}\n\n"
            f"Previously tried queries (do NOT repeat):\n{prior_queries_str}\n\n"
            f"Retrieved evidence so far:\n{retrieved_chunks_str}\n\n"
            f"Uncovered checklist items:\n{uncovered_str}\n\n"
            f"Human feedback (if any):\n{human_feedback}"
        )
        message = HumanMessage(content=context)

    hop_count = state.get("hop_count", 0)
    print(
        f"[decompose] invoking LLM ({'grounding' if is_grounding_hop else 'decomposition'} prompt)"
    )
    result = decompose_model.invoke([sys_prompt, message])
    queries = result.queries
    print(
        f"[decompose] transform LLM.result -> queries | after: {queries[:3]}... (count={len(queries)})"
    )
    checklist = state.get("checklist", [])
    if not is_grounding_hop:
        new_checklist = (
            result.checklist if hop_count < 3 else state.get("checklist", [])
        )
        print(
            f"[decompose] transform LLM.result -> checklist | before: {checklist[:2]}... (count={len(checklist)}) | after: {new_checklist[:2]}... (count={len(new_checklist)})"
        )
        checklist = new_checklist

    print(
        f"[decompose] EXIT hop={hop_count_in} queries={len(queries)} checklist={len(checklist)}"
    )
    return {
        "current_decompose_queries": queries,
        "total_decompose_queries": queries,  # appended via operator.add
        "human_feedback": "",  # clear after consumption
        "checklist": checklist,
    }
