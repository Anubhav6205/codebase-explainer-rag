from langchain.messages import HumanMessage, SystemMessage
from langchain.chat_models import init_chat_model
from pydantic import BaseModel, Field, field_validator

import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from state import MessageState


class CoverageCheckOutput(BaseModel):
    coverage_mapping: dict[str, list[str]] = Field(
        description="For each checklist item (verbatim key), the list of chunk ids that substantively cover it. Empty list if none."
    )

    @field_validator("coverage_mapping", mode="before")
    @classmethod
    def coerce_ids_to_str(cls, v):
        if isinstance(v, dict):
            return {k: [str(i) for i in vals] for k, vals in v.items()}
        return v


coverage_check_model = init_chat_model("gpt-4.1-mini").with_structured_output(
    CoverageCheckOutput,
    method="function_calling",
)


COVERAGE_CHECK_SYS = SystemMessage(content="""\
You are the coverage checker for a codebase Q&A agent. You do NOT synthesise an
answer. You do NOT retrieve. You judge one thing only, item-by-item:

    "Does this chunk contain information that would let a reader ANSWER this
     checklist item?"

You will receive:
- The original user question (for context only)
- A checklist of sub-questions that MUST all be answered for the final answer
  to be considered complete
- A pool of retrieved chunks, each tagged with a unique id

Your output:
- A `coverage_mapping` dict whose keys are the checklist items VERBATIM (exact
  string match — do not rephrase) and whose values are the list of chunk ids
  that substantively cover that item. Empty list if no chunk covers it.

STRICTNESS RULES — read carefully. Over-generous coverage is the failure mode
that ruins the entire system.

1. SUBSTANTIVE, not superficial. A chunk covers an item only if it contains the
   actual answer, or the code/definition/logic that answers it. Chunks that
   merely mention the topic — a passing reference, an import statement, a
   comment name-drop — do NOT count.

2. LITERAL relevance. Do not infer. If the item asks "where is X defined?" a
   chunk that uses X but does not define it is NOT coverage. A chunk that
   defines X IS coverage.

3. One chunk can cover multiple items. Emit its id in every item's list where
   it substantively covers.

4. Multiple chunks can cover one item. Include ALL of them, not just the best.

5. Empty is fine. If nothing in the chunk pool covers an item, its value is [].
   Do not invent partial coverage to avoid an empty list.

6. Key discipline. Every checklist item you were given MUST appear as a key in
   `coverage_mapping`, verbatim. Do not add keys that were not in the checklist.
   Do not omit keys.

7. NON-EXISTENCE signal. If the checklist item asks about a specific named
   class, function, or constant and that exact name does not appear verbatim
   in ANY chunk in the pool, that item CANNOT be covered — do not substitute
   a topically similar class or a class with a similar name. An empty list
   is the correct output in this case.

Return only the `coverage_mapping` field.
""")


def _format_chunks(chunks):
    if not chunks:
        return "(no chunks retrieved yet)"
    return "\n\n".join(
        f"[id={c['id']}] file={c.get('source_file') or c.get('headers') or '?'}\n{c['text'][:800]}"
        for c in chunks
    )


def _format_checklist(items):
    if not items:
        return "(empty)"
    return "\n".join(f"- {item}" for item in items)


def coverage_check_agent(state: MessageState) -> dict:
    checklist = state.get("checklist", []) or []
    retrieved_chunks = state.get("retrieved_chunks", []) or []
    question = state.get("question", "")
    print(f"[coverage_check] ENTER checklist_items={len(checklist)} chunks_in_pool={len(retrieved_chunks)}")

    # Hop 1 has no real checklist yet — force loop back
    if not checklist:
        print(f"[coverage_check] EXIT is_sufficient=False (empty checklist, hop 1 short-circuit)")
        return {
            "coverage_map": {},
            "is_sufficient": False,
        }

    checklist_str = _format_checklist(checklist)
    chunks_str = _format_chunks(retrieved_chunks)
    print(f"[coverage_check] transform checklist(list) -> str | before: {checklist[:1]}... (count={len(checklist)}) | after: str(len={len(checklist_str)})")
    print(f"[coverage_check] transform retrieved_chunks(list) -> str | before: list(len={len(retrieved_chunks)}) | after: str(len={len(chunks_str)})")

    context = (
        f"Original question:\n{question}\n\n"
        f"Checklist (each item must be covered):\n{checklist_str}\n\n"
        f"Retrieved chunk pool:\n{chunks_str}"
    )

    print(f"[coverage_check] invoking LLM")
    result = coverage_check_model.invoke(
        [COVERAGE_CHECK_SYS, HumanMessage(content=context)]
    )

    coverage_map = result.coverage_mapping
    print(f"[coverage_check] transform LLM.result -> coverage_mapping(dict) | after: keys_returned={len(coverage_map)} (expected={len(checklist)})")

    # Guard: model may drop/rename keys — reconcile against the true checklist
    reconciled = {item: coverage_map.get(item, []) for item in checklist}
    covered_count = sum(1 for v in reconciled.values() if v)
    print(f"[coverage_check] transform coverage_map -> reconciled | before: {len(coverage_map)} keys | after: {len(reconciled)} keys ({covered_count} covered, {len(reconciled) - covered_count} uncovered)")

    is_sufficient = all(bool(v) for v in reconciled.values())
    print(f"[coverage_check] EXIT is_sufficient={is_sufficient}")

    return {
        "coverage_map": reconciled,
        "is_sufficient": is_sufficient,
    }
