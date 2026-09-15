from langchain.messages import HumanMessage, SystemMessage
from langchain.chat_models import init_chat_model
from pydantic import BaseModel, Field

import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from state import MessageState

MAX_CITATION_RETRIES = 2


class CitationCheckOutput(BaseModel):
    supported: bool = Field(
        description="True if the union of cited chunks LITERALLY supports the entire claim, false otherwise"
    )
    unsupported_reason: str = Field(
        description="If supported is false, one short line stating what fact is missing. Empty string if supported is true."
    )


citation_check_model = init_chat_model("gpt-5-mini").with_structured_output(
    CitationCheckOutput
)


CITATION_CHECK_SYS = SystemMessage(content="""\
You are the citation verifier for a codebase Q&A agent. You do NOT retrieve.
You do NOT synthesise. You do NOT judge whether the answer is complete or
whether the claim is a good claim to make. You judge one thing only:

    "Do these chunks, TAKEN TOGETHER, LITERALLY support this specific claim?"

You will receive:
- One claim from the agent's answer (a single factual statement)
- A list of cited chunk ids and the full text of each

Your output:
- `supported`: true if the UNION of the cited chunks literally contains the
  facts stated in the claim, false otherwise
- `unsupported_reason`: one short line naming what fact is missing when
  supported is false; empty string when supported is true

STRICTNESS RULES — read carefully.

1. LITERAL support only. The chunks must contain the specific facts stated in
   the claim. Being "about the same topic", "mentioning the identifier", or
   "importing the module" is NOT support.

2. Consider chunks TOGETHER, not atomically. A multi-part claim may be
   supported by multiple chunks between them — one chunk provides part A,
   another chunk provides part B. That counts as supported as long as the
   UNION of the cited chunks contains every fact in the claim. Do NOT reject
   a valid multi-chunk citation just because no single chunk carries the
   whole claim.

3. Do NOT rescue overreach. If the claim generalises beyond what the chunks
   collectively say (e.g. claim says "always rejects" but chunks show only one
   rejection condition), supported is false.

4. Do NOT verify against your world knowledge. Only against the chunk text
   provided. If the claim is true in reality but the chunks do not state it,
   supported is false.

5. Do NOT downgrade to partial. `supported` is strictly true or false. If in
   doubt, supported is false and name the missing fact in `unsupported_reason`.

6. Do NOT invent chunks. Judge only against the chunks that were actually
   cited and shown to you.

Return only the `supported` and `unsupported_reason` fields.
""")


def _format_cited_chunks(chunk_ids, all_chunks):
    id_to_chunk = {str(c["id"]): c for c in all_chunks}
    lines = []
    for cid in chunk_ids:
        chunk = id_to_chunk.get(str(cid))
        if chunk is None:
            lines.append(f"[id={cid}] (MISSING FROM POOL — treat as unsupported)")
            continue
        loc = chunk.get("source_file") or chunk.get("headers") or "?"
        lines.append(f"[id={cid}] file={loc}\n{chunk['text']}")
    return "\n\n".join(lines) if lines else "(no chunks cited)"


def citation_check_agent(state: MessageState) -> dict:
    citations = state.get("citations", []) or []
    retrieved_chunks = state.get("retrieved_chunks", []) or []
    retry_count = state.get("citation_retry_count", 0)

    # Exhausted answers carry empty citations — trivially pass
    if not citations:
        return {"citation_passed": True}

    failed_claims = []
    for cit in citations:
        claim = cit["claim"]
        chunk_ids = cit["chunk_ids"]

        context = (
            f"Claim:\n{claim}\n\n"
            f"Cited chunks:\n{_format_cited_chunks(chunk_ids, retrieved_chunks)}"
        )

        result = citation_check_model.invoke(
            [CITATION_CHECK_SYS, HumanMessage(content=context)]
        )

        if not result.supported:
            failed_claims.append(
                {"claim": claim, "reason": result.unsupported_reason}
            )

    if not failed_claims:
        return {"citation_passed": True}

    # Failed — check retry budget
    if retry_count >= MAX_CITATION_RETRIES:
        return {
            "citation_passed": False,
            "citation_retry_count": retry_count,
            "answer": "Citations could not be verified against source.",
            "termination_reason": "citation_verification_failed",
        }

    return {
        "citation_passed": False,
        "citation_retry_count": retry_count + 1,
        "human_feedback": "Citation verification failed on: "
        + "; ".join(f"'{fc['claim']}' ({fc['reason']})" for fc in failed_claims),
    }
