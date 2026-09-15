# Agent Layer — Self-Contained Completion Checklist

Reference for finishing the agent layer (Step 8 remainder + Step 9) in one sitting.

---

## Fixes first (10 min)

- **`agents/decompose.py`**: init `checklist = state.get("checklist", [])` before the `if is_grounding_hop` block — else `NameError` on hop 1
- **`state.py`**: drop legacy `is_found`
- **`ingest/ingestion/dense/docs.py`**: add `source_file` to payload → re-ingest `dense_docs` (blocks citation display for doc chunks)
- **`graph/graph.py`**: currently uses `searcher_agent` — your file exports `searcher`. Rename one or the other so imports match

---

## `agents/coverage_check.py` (30–45 min)

- **Reads:** `checklist`, `retrieved_chunks`, `question`
- For each checklist item, LLM call: *"Which of these chunks (by id) address this sub-question? Return list of ids, empty if none."* — batch per-item OR batch all items in one call if you can guarantee structured output
- Build `coverage_map: dict[str, list[str]]` = `{item: [chunk_ids]}`
- `is_sufficient = all(bool(v) for v in coverage_map.values())` — arithmetic, never LLM opinion
- **Return:** `{"coverage_map": coverage_map, "is_sufficient": is_sufficient}`
- **Gotcha:** if `checklist` is empty (hop 1), return `is_sufficient=False` (force loop back) — special-case at top of function
- **Prompt rule:** forbid the LLM from claiming coverage when chunk text doesn't literally address the item. Under-coverage > over-coverage.

---

## `agents/response.py` (30 min)

- **Reads:** `question`, `retrieved_chunks`, `is_sufficient`, `coverage_map`, `hop_count`
- Two branches:
  - **Sufficient:** LLM synthesizes cited answer. Pydantic output: `{answer: str, citations: list[{claim: str, chunk_ids: list[str]}]}`. Format prompt so every factual claim is tagged with the chunk id it came from.
  - **Exhausted** (route sent it here with `is_sufficient=False` after hop cap): emit `"This question cannot be answered from this repository."` and set `termination_reason = "exhausted"`. Skip citations.
- **Return:** `{"answer": ..., "citations": ..., "termination_reason": ...}` — add `citations` field to `state.py`

---

## `agents/citation_check.py` (30 min)

- **Reads:** `answer`, `citations`, `retrieved_chunks`
- For each claim, LLM call: *"Does chunk-id X literally support this claim? YES / NO / PARTIAL."*
- `citation_passed = all(verdict == "YES" for verdict in verdicts)` — strict
- On fail: check `citation_retry_count`
  - `< MAX_CITATION_RETRIES` → return `{"citation_passed": False, "citation_retry_count": count+1}` — route sends back to `response`
  - `>= MAX` → return `{"citation_passed": False, "termination_reason": "citation_verification_failed", "answer": "Citations could not be verified against source."}`
- **Toolless:** no retrieval calls here. If a claim isn't in the chunks, that's a synthesis failure, not an evidence failure.

---

## `agents/human_verify.py` (15 min)

- **Reads:** `answer`, `citations`, `termination_reason`, `EVAL_MODE` env var
- If `EVAL_MODE=true` → auto-return `{"human_decision": "approve", "termination_reason": "approved"}` — bypass entirely
- Else: `input()` prompt showing answer + citations, ask for `approve` / `reject` / `feedback:<text>`
- Parse:
  - `approve` → `{"human_decision": "approve", "termination_reason": "approved"}`
  - `reject` → `{"human_decision": "reject_no_feedback", "termination_reason": "rejected_no_feedback"}`
  - `feedback:<text>` → `{"human_decision": "reject_with_feedback", "human_feedback": text}` + bump `human_retry_count`
- **Add to `state.py`:** `human_retry_count: int`, `citations: list[dict]`
- **Add to `graph/graph.py`:** `MAX_HUMAN_RETRIES = 2` constant
- **Route from HITL:** `reject_with_feedback` + `human_retry_count < MAX_HUMAN_RETRIES` → `decompose`, else → `END`

---

## `graph/graph.py` — wiring

- Replace stub `*_agent` functions with real imports from `agents/`
- Ensure conditional-edge dict maps match all router return values (currently `route_citation_check` returns `"human_verify"` or `"response"`; verify HITL route mapping includes `END` and `"decompose"`)
- **Route `route_coverage_check`:**
  - Hop 1 special case: `if state.get("checklist") is None or len(state.get("checklist", [])) == 0: return "decompose"` (skip response until real checklist exists)
  - Existing logic otherwise
- **No-progress detection** in `route_coverage_check`: if `hop_count > 1` and no new chunks were added this hop → route to `response` (will abstain). Track via `chunks_added_this_hop: int` set by searcher.

---

## State fields to add

- `citations: list[dict]`
- `citation_retry_count: int` (already there — verify)
- `human_retry_count: int`
- `termination_reason: str` (already there)
- `chunks_added_this_hop: int` (for no-progress detection)

---

## Test order (do not skip)

1. **Q3 (`how-X-works`, small gold set)** — simplest question, minimum hops needed. If this fails, everything else will.
2. **Q1 (relational, 4 gold files)** — stresses the 6-point checklist template
3. **Q22 (plausible-absent)** — must abstain within hop cap. If it synthesizes a confident answer, coverage_check is too lenient.
4. **Q26 (off-topic)** — must abstain by hop 1 or 2.

---

## Order that avoids rework

1. Fixes (decompose bug, state cleanup, graph import name)
2. `coverage_check` → wire it → test hop 2 loops correctly with stub `response`
3. `response` (both branches) → wire → test end-to-end on Q3
4. `citation_check` (with retry) → wire → test on Q3 again
5. `human_verify` with `EVAL_MODE=true` → wire → run headless on Q3, Q1, Q22, Q26
6. Manual `EVAL_MODE=false` run once — sanity check HITL prompt flow

---

## Time-boxed budget

| Task | Time |
|---|---|
| Fixes | 15m |
| coverage_check + wire + smoke | 45m |
| response + wire + smoke | 45m |
| citation_check + wire + smoke | 45m |
| human_verify + wire + eval-mode | 30m |
| 4-question end-to-end pass | 30m |

**Total: ~3.5h** if nothing surprises you. Add 1h buffer.

---

## Failure modes to watch

- Coverage_check LLM says "YES" too readily → sufficiency triggers on hop 1, agent never loops
- Response cites chunk ids that aren't in `retrieved_chunks` → citation_check fails immediately, loops forever until retry cap
- Decompose rewrites checklist on every hop → coverage_map keys drift, coverage seems to reset
- No-progress detection missing → plausible-absent questions loop until hop cap, wasting tokens
- HITL blocks on `input()` in headless eval → never terminates
