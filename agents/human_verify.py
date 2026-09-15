from langchain.messages import HumanMessage, SystemMessage
from langchain.chat_models import init_chat_model
from langgraph.types import interrupt
from pydantic import BaseModel, Field

import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from state import MessageState


class HumanVerifyOutput(BaseModel):
    decision: str = Field(
        description="Tells whether human approved the answer, rejected with feedback, or rejected without feedback. Holds either 'approve', 'reject_no_feedback','reject_with_feedback'"
    )
    feedback: str = Field(description="Holds user's feedback")


HUMAN_VERIFY_SYS = SystemMessage(content="""\
You are the classifier for a human reviewer's response to a codebase Q&A
agent's answer. You do NOT retrieve. You do NOT synthesise. You do NOT
evaluate the answer's correctness yourself. Your only job is to translate
the human's freeform reply into one of exactly three outcomes.

You will receive:
- The agent's answer that was shown to the human
- The human's freeform reply

Return one of exactly three `decision` values:

1. `approve`
   The human accepted the answer as-is. Signals: "approve", "accept",
   "looks good", "lgtm", "yes", "correct", "ship it", a bare thumbs-up,
   or any clear affirmation.

2. `reject_no_feedback`
   The human rejected the answer but gave no actionable guidance for a
   retry. Signals: bare "reject", "no", "wrong", "bad", a bare
   thumbs-down, expressions of dissatisfaction with no suggestion for
   what to fix or search differently.

3. `reject_with_feedback`
   The human rejected the answer AND provided guidance the agent could act
   on for another hop — a missed source, a wrong interpretation, a term to
   look up, a facet that was skipped, or an explicit correction. If there
   is ANY substantive guidance beyond dissatisfaction, choose this over
   `reject_no_feedback`.

STRICTNESS RULES:

1. Bias against `reject_with_feedback` UNLESS the human genuinely gave
   actionable guidance. "This is wrong" alone is `reject_no_feedback`.
   "This is wrong, you missed the FieldFormatEntityPolicy" is
   `reject_with_feedback`.

2. Ambiguous or empty replies default to `reject_no_feedback` — never
   `approve`. Absence of clear affirmation is not approval.

3. If the human offers guidance AND explicitly approves ("looks fine, but
   also mention X"), treat as `approve`. Do not loop back on stylistic
   nice-to-haves.

4. If `decision` is `reject_with_feedback`, populate `feedback` with the
   guidance verbatim from the human's reply — do not paraphrase, do not
   summarise, do not add analysis. For all other decisions, `feedback` is
   an empty string.

Return only the `decision` and `feedback` fields.
""")

EVAL_MODE = os.getenv("EVAL_MODE", "false").lower() == "True"

human_verify_model = init_chat_model("gpt-5-mini").with_structured_output(
    HumanVerifyOutput
)


def _format_citations(citations: list):
    response = ""
    for citation in citations:
        merged_chunk_ids = ",".join(citation.get("chunk_ids",[]))
        claim = citation.get("claim")
        response += f"{claim} - {merged_chunk_ids} \n\n"
    return response


def human_verify_agent(state: MessageState):
    answer = state.get("answer")
    citations = state.get("citations")
    termination_reason = state.get("termination_reason")

    if EVAL_MODE:
        return {"human_decision": "approve", "termination_reason": "approved"}

    human_input = interrupt(
        {"answer": answer, "question": "Approve? If no, provide feedback"}
    )

    context = (
        f"Answer: {answer} \n\n"
        f"Citations: {_format_citations(citations)}\n\n"
        f"Termination Reson: {termination_reason}\n\n"
        f"Human Input: {human_input}\n\n"
    )

    result = human_verify_model.invoke(
        [HUMAN_VERIFY_SYS, HumanMessage(content=context)]
    )

    decision = result.get("decision")

    if decision == "approve":
        return {"human_decision": "approve", "termination_reason": "approved"}
    elif decision == "reject_no_feedback":
        return {
            "human_decision": "reject_no_feedback",
            "termination_reason": "rejected_no_feedback",
        }
    else:
        return {
            "human_decision": "reject_with_feedback",
            "human_feedback": result.feedback,
            "human_retry_count": state.get("human_retry_count", 0) + 1,
        }
