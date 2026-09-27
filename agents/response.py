from langchain.messages import HumanMessage, SystemMessage
from langchain.chat_models import init_chat_model
from pydantic import BaseModel, Field

import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from state import MessageState


class Citation(BaseModel):
    claim: str = Field(
        description="A single factual claim from the answer, quoted or paraphrased verbatim"
    )
    chunk_ids: list[str] = Field(
        description="Chunk ids that literally support this claim"
    )


class ResponseOutput(BaseModel):
    answer: str = Field(
        description="The final answer to the user's question, written as clean short bullet points"
    )
    citations: list[Citation] = Field(
        description="One entry per factual claim in the answer, tagged with the chunk ids that support it"
    )


response_model = init_chat_model("gpt-4.1-mini").with_structured_output(ResponseOutput)


RESPONSE_SYS = SystemMessage(content="""\
You are the answer synthesiser for a codebase Q&A agent. Coverage_check has
already ruled the retrieved evidence sufficient. You do NOT retrieve. You do
NOT judge sufficiency. You do NOT abstain — the router only sends you here
when synthesis is warranted.

You will receive:
- The original user question
- The checklist (sub-questions that must be answered)
- The coverage_map (which chunk ids cover which checklist item)
- The full retrieved chunk pool (id + file + text)

Your job — produce TWO things:

--------------------------------------------------------------------------
1. `answer` — the response to the user
--------------------------------------------------------------------------
- Written in clean short bullet points
- Each bullet addresses one checklist item, in the order the items appear
- Reference specific identifiers, file paths, and concrete facts from the
  chunks — no vague generalities
- Do NOT invent facts not present in the chunks
- Do NOT include chunk ids inline in the prose — those go in `citations`
- If a checklist item has no supporting chunks in coverage_map (should be rare
  since coverage_check gated this), skip that bullet rather than fabricate

--------------------------------------------------------------------------
2. `citations` — one entry per factual claim
--------------------------------------------------------------------------
- Every factual claim in `answer` must appear as a Citation entry
- `claim` = the exact phrase/sentence from the answer (verbatim or close paraphrase)
- `chunk_ids` = the chunk ids that LITERALLY support this claim — not "related"
  chunks, only the ones that contain the answer

STRICTNESS RULES:

1. LITERAL support only. A chunk that mentions the topic but doesn't state the
   fact is NOT a supporting citation for that claim.
2. Minimum one chunk id per claim. If you can't back a claim with at least one
   chunk id from the pool, do not make the claim.
3. Prefer chunk ids that also appear in coverage_map for the relevant checklist
   item — they've already been vetted.
4. Never cite a chunk id that isn't in the retrieved chunk pool.

Return only `answer` and `citations`.
""")


def _format_chunks(chunks):
    if not chunks:
        return "(none)"
    return "\n\n".join(
        f"[id={c['id']}] file={c.get('source_file') or c.get('headers') or '?'}\n{c['text']}"
        for c in chunks
    )


def _format_checklist(items):
    if not items:
        return "(none)"
    return "\n".join(f"- {item}" for item in items)


def _format_coverage_map(coverage_map):
    if not coverage_map:
        return "(none)"
    lines = []
    for item, ids in coverage_map.items():
        ids_str = ", ".join(ids) if ids else "(no chunks)"
        lines.append(f"- {item}\n  covered by: {ids_str}")
    return "\n".join(lines)


def response_agent(state: MessageState) -> dict:
    is_sufficient = state.get("is_sufficient", False)
    hop_count = state.get("hop_count", 0)
    print(f"[response] ENTER hop={hop_count} is_sufficient={is_sufficient}")

    # Exhausted branch — router sent us here after hop cap with is_sufficient=False
    if not is_sufficient:
        print(f"[response] EXIT abstain (termination_reason=exhausted)")
        return {
            "answer": "This question cannot be answered from this repository.",
            "citations": [],
            "termination_reason": "exhausted",
        }

    # Sufficient branch — synthesise a cited answer
    question = state.get("question", "")
    checklist = state.get("checklist", []) or []
    coverage_map = state.get("coverage_map", {}) or {}
    retrieved_chunks = state.get("retrieved_chunks", []) or []
    print(
        f"[response] transform inputs -> context | before: checklist(len={len(checklist)}) coverage_map({len(coverage_map)} keys) chunks(len={len(retrieved_chunks)})"
    )

    checklist_str = _format_checklist(checklist)
    coverage_str = _format_coverage_map(coverage_map)
    chunks_str = _format_chunks(retrieved_chunks)
    print(
        f"[response] transform lists/dicts -> strs | after: checklist_str(len={len(checklist_str)}) coverage_str(len={len(coverage_str)}) chunks_str(len={len(chunks_str)})"
    )

    context = (
        f"Original question:\n{question}\n\n"
        f"Checklist (answer plan):\n{checklist_str}\n\n"
        f"Coverage map (item -> chunk ids that cover it):\n{coverage_str}\n\n"
        f"Retrieved chunk pool (full text):\n{chunks_str}"
    )

    print(f"[response] invoking LLM")
    result = response_model.invoke([RESPONSE_SYS, HumanMessage(content=context)])

    citations_dumped = [c.model_dump() for c in result.citations]
    print(
        f"[response] transform Citation(BaseModel) -> dict | before: {len(result.citations)} Citation objects (sample: claim={result.citations[0].claim[:60]!r}... chunk_ids={result.citations[0].chunk_ids}) | after: {len(citations_dumped)} dicts"
        if result.citations
        else f"[response] transform Citation(BaseModel) -> dict | before: 0 Citation objects | after: 0 dicts"
    )
    print(
        f"[response] EXIT answer_len={len(result.answer)} citations={len(citations_dumped)}"
    )

    return {
        "answer": result.answer,
        "citations": citations_dumped,
    }
