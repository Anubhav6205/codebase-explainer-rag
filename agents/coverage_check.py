from langchain.messages import HumanMessage, SystemMessage
from langchain.chat_models import init_chat_model
from pydantic import BaseModel, Field

import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from state import MessageState


class CoverageCheckOutput(BaseModel):
    coverage_mapping: dict[str, list[str]] = Field(
        description="For each checklist item (verbatim key), the list of chunk ids that substantively cover it. Empty list if none."
    )


coverage_check_model = init_chat_model("gpt-5-mini").with_structured_output(
    CoverageCheckOutput
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

    # Hop 1 has no real checklist yet — force loop back
    if not checklist:
        return {
            "coverage_map": {},
            "is_sufficient": False,
        }

    context = (
        f"Original question:\n{question}\n\n"
        f"Checklist (each item must be covered):\n{_format_checklist(checklist)}\n\n"
        f"Retrieved chunk pool:\n{_format_chunks(retrieved_chunks)}"
    )

    result = coverage_check_model.invoke(
        [COVERAGE_CHECK_SYS, HumanMessage(content=context)]
    )

    coverage_map = result.coverage_mapping

    # Guard: model may drop/rename keys — reconcile against the true checklist
    reconciled = {item: coverage_map.get(item, []) for item in checklist}

    is_sufficient = all(bool(v) for v in reconciled.values())

    return {
        "coverage_map": reconciled,
        "is_sufficient": is_sufficient,
    }
