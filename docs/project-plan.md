# Codebase Explainer — Capstone Plan

**Locked:** Sep 1, 2026 · **Ship date:** Sep 13, 2026 · **Budget:** ~27 focused hours

---

## 1. The problem statement (README version)

### The problem

When a new engineer joins a team, their first two weeks are spent asking questions
that nobody has time to answer twice:

> *"How does authentication actually work in this service?"*

The answer is never in one place. It's split across a README, an architecture
decision record, a middleware file, a config module, and a utility function three
directories away. A human answers this by reading one thing, realising something is
missing, going to find it, and repeating until the picture is complete.

Standard RAG chatbots cannot do this. They retrieve once, get a plausible-looking
chunk, and answer confidently from an incomplete picture. The answer sounds right
and is missing half the system.

### What this does

This is a codebase onboarding assistant that answers architectural questions about a
repository by gathering evidence across multiple sources — the way a human would.

Given a question, it:

1. Searches the codebase and its documentation together
2. Checks whether what it found is actually *sufficient* to answer
3. If something is missing, rewrites its query and searches again
4. Answers with a citation for every claim, pointing at the exact file or doc
5. Says **"I don't have enough information"** when the repo genuinely doesn't cover it

### Why it's built this way

Three design decisions that are worth stating explicitly:

- **Retrieval lives inside the reasoning loop, not in front of it.** The system does
  not retrieve once and generate. It decides, mid-answer, whether it needs another hop.
- **Hybrid search, not just semantic.** Pure vector search misses exact identifiers —
  function names, config keys, class names. Keyword search misses "how does auth work"
  phrased in words that appear nowhere in the code. Both are needed.
- **Abstention is a feature.** The system is evaluated on whether it correctly refuses
  to answer, not just on whether it answers well. A confidently wrong answer about a
  codebase is worse than no answer.

### How it's evaluated

A golden set of ~30 questions, each labelled with the **complete set of sources** required
to answer it. Metrics:

- **Retrieval recall** — did it find *all* required sources, not just one relevant one?
- **Faithfulness** — is every claim supported by a cited chunk?
- **Citation precision** — does each cited chunk actually support the claim attached to it?
- **Abstention accuracy** — on deliberately unanswerable questions, did it correctly refuse?
- **False-confidence rate** — how often did it declare its evidence sufficient while
  missing a required source? This is the headline number. Wasted hops cost money;
  false confidence is the failure that actually matters

Evals run in CI and gate merges on a quality threshold.

---

## 2. Build order — strict sequence

Do not start step N+1 until step N is done and working. Each step lists the skills it
exercises so you know what you're practising when.

### PHASE 1 — Foundation

**Step 1. Problem and scope** *(design)*
- Write the README problem statement above into the repo
- Pick the target repository to index (mid-size, good docs, real ADRs)
- **Repo must have distinctive domain vocabulary** — entity names specific to that project,
  not just generic `UserService` / `Controller` naming. Without domain nouns, every question
  becomes "how does auth work" and the hard case never gets exercised
- Decide what "a question about this repo" looks like — write 5 example questions,
  at least 2 of them relational ("how does X associate to Y")
- *Skills: none technical — this is the step that signals seniority in interviews*

**Step 2. Architecture design** *(design)*
- Draw the node/edge graph, define the state object, list the tools
- Decide max hop count and what triggers a re-query
- *Skills: LangGraph (design-level — state shape, conditional edges)*

**Step 3. Environment setup**
- Repo, config, `.env` handling, `pyproject`
- `docker-compose.yml` bringing up Qdrant + a placeholder app service
- Verify Qdrant is reachable and you can create a collection
- *Skills: **Docker**, **Qdrant** (setup)*

### PHASE 2 — Retrieval (the layer you're actually here to learn)

**Step 4. Corpus ingestion**
- Clone target repo, walk the tree
- Chunk code AST-aware (function/class level — not character splits)
- Chunk docs/ADRs semantically (topic boundaries)
- Attach metadata to every chunk: file path, type, symbol name
- Embed and index into Qdrant
- *Skills: **RAG** (chunking strategy), **LangChain** (splitters, embeddings), **Qdrant** (indexing, payload metadata)*

**Step 5. Hybrid retrieval + reranking**
- Dense vector search over the collection
- BM25 / sparse search over the same corpus
- Fuse both with Reciprocal Rank Fusion → top ~50
- Cross-encoder rerank → top ~5
- Compare results at each stage manually and note what changed
- *Skills: **RAG** (hybrid search, RRF, reranking), **Qdrant** (sparse + dense vectors)*

> **Checkpoint:** you should now be able to query the corpus from a script and get
> visibly better results than dense-only. If you can't demonstrate that difference,
> do not proceed — the rest of the project rests on this layer.

### PHASE 3 — Measurement before intelligence

**Step 6. Golden dataset**
- Write ~30 questions against the target repo
- ~20 answerable, each labelled with the **full set** of files/docs needed
  - Mix question types deliberately: "how does X work", "how does X associate to Y",
    "what happens when X fails". Relational questions decompose differently and are
    the ones that stress multi-hop
- ~10 deliberately unanswerable, and make them adversarial rather than obviously off-topic:
  - 3 using **plausible-but-absent domain nouns** — terms that sound like they belong to
    this project but aren't in it. These are what catch false confidence
  - 1 built on a **homonym** (e.g. a term meaning something different here than in the
    obvious reading) to test disambiguation
  - the rest genuinely outside the repo's scope
- Store as versioned JSON in the repo
- *Skills: **Golden Datasets***

**Step 7. Baseline retrieval eval**
- Run the golden set against the Step 5 retriever
- Measure context precision and recall with Ragas
- **Record these numbers.** They are your "before" for the improvement story
- *Skills: **Ragas**, eval methodology*

> **Why this order:** measuring retrieval *before* adding the agent means you can prove
> the agent improved things. Build the agent first and you can never separate the two.

### PHASE 4 — Agent

**Step 8. Agent layer** — build in this sub-order, it is the hardest step

- **8a. Graph skeleton.** `StateGraph` + state object that accumulates evidence across hops.
  Wire both search tools. Get a single pass working end to end with a stub sufficiency check
  that always says "sufficient" — prove the plumbing before the intelligence
- **8b. Grounding pass.** Before decomposing anything, resolve the domain nouns in the
  question against the repo: what is this term here — an entity, a service, a table, a
  config key? Hybrid search matters most here, since domain nouns hit BM25 exactly
- **8c. Question-type classifier.** Route to the right decomposition template.
  "How does X work" and "how does X associate to Y" need different checklists —
  the relational one must cover: what each side is, where they touch, direction and
  cardinality, where the relationship is *enforced*, and what happens when it's violated
- **8d. Decomposition into a checklist**, with grounding evidence in context.
  Output sub-questions, not a verdict
- **8e. Coverage mapping.** For each sub-question, map to a chunk or mark uncovered.
  Sufficiency becomes arithmetic over that list, never a yes/no opinion
- **8f. Loop control.** Uncovered items become the next query. Hard hop cap,
  plus no-progress detection (if a hop returns only chunks already held, stop)
- *Skills: **LangGraph** (StateGraph, conditional edges, state accumulation), **Tool Calling**, **Agentic Workflows**, **Claude***

> **Why this sub-order:** asking a model "is this enough?" directly gets "yes" almost every
> time. Sufficiency only works as coverage-against-an-enumerated-checklist, and the checklist
> can only be written after the domain vocabulary is grounded. Build it in the wrong order
> and you get an agent that confidently answers from half the picture.

**Step 9. Synthesis and critique**
- Synthesis node: answer with per-claim citations, Pydantic-structured output
- Critique node: verify each citation actually supports its claim
- Abstention path: explicit "not covered by this repo" output
- *Skills: **Claude**, structured output, **LLM-as-Judge** (the critique pass is one)*

**Step 10. Reliability**
- Retries, timeouts, graceful degradation when a hop fails
- Handle the case where reranking returns nothing useful
- *Skills: production hardening*

### PHASE 5 — Prove it

**Step 11. Full eval harness**
- Ragas: faithfulness + context recall on the full pipeline
- LLM-as-judge: answer quality and citation correctness
- promptfoo: regression suite over the sufficiency and synthesis prompts.
  **Weight it toward decomposition quality on domain-specific vocabulary** — coverage
  against a badly-decomposed checklist tells you nothing, so this prompt is the one
  most worth regression-testing as you tune it
- Report the false-confidence rate alongside recall — it's the metric interviewers
  will not have heard from other candidates
- Wire into GitHub Actions, gate merges on threshold
- **Compare against the Step 7 baseline — this is your headline number**
- *Skills: **Ragas**, **promptfoo**, **LLM-as-Judge**, CI gating*

**Step 12. Observability**
- LangSmith tracing (cloud) — trace hop counts, per-node latency, token cost
- Phoenix (local) — same traces, local
- Note the trade-offs between them; you'll be asked
- *Skills: **LangSmith**, **Phoenix***

### PHASE 6 — Ship

**Step 13. Serving layer**
- FastAPI async endpoint over the graph, streaming the answer
- *Skills: **FastAPI**, **AsyncIO***

**Step 14. MCP server**
- Expose `search_code` and `search_docs` as MCP tools via FastMCP
- Demo working in Claude Desktop
- *Skills: **MCP***

**Step 15. Package, docs, demo**
- Full docker-compose: app + Qdrant + MCP server
- README with the architecture diagram and the before/after eval numbers
- 2-minute recorded demo
- *Skills: **Docker**, presentation*

---

## 3. Agents and tools

### There is one agent, not several

This is a single-agent graph. Most nodes are deterministic — they run the same way every
time, so they are nodes, not tools. Only the sufficiency loop involves a genuine runtime
decision, and that is where the agent lives.

| Component | Type | Purpose | Holds tools? |
|---|---|---|---|
| `ingest` | Offline script | Chunk and index the repo. Runs once, not per query | No |
| `retrieve` | Node | Hybrid search + RRF + rerank. Deterministic given a query | No |
| **`sufficiency_agent`** | **Agent** | Grounds domain terms, decomposes the question into a checklist, maps evidence to it, and hops again on whatever is uncovered | **Yes — both search tools** |
| `synthesize` | Node | Turn accumulated evidence into an answer with per-claim citations | No |
| `critique` | Node | Second LLM pass verifying each citation supports its claim | No — deliberately toolless |
| `abstain` | Node | Emit "not covered by this repo" with what was searched | No |

### The two tools

| Tool | Signature | Held by | Why it's a tool and not a node |
|---|---|---|---|
| `search_code` | `(query: str) -> list[Chunk]` | `sufficiency_agent` | The agent decides *when* to call it and *what* to ask — that's a runtime decision |
| `search_docs` | `(query: str) -> list[Chunk]` | `sufficiency_agent` | Separate from code search because the agent must be able to choose which corpus to hop into |

**Design principle:** deterministic steps are nodes; only genuine runtime decisions become
tools. `retrieve` always runs identically on the first pass, so it's a node. The *second*
and later retrievals are agent-initiated, so those go through tools.

**Why `critique` holds no tools:** if the critic could retrieve, it would paper over gaps
by fetching new evidence instead of flagging that the answer was under-supported. Keeping
it toolless is what makes it a real check.

### Control flow

```
                    ┌─────────────────────────┐
                    │  ingest and index       │  (offline, run once)
                    │  AST chunks + doc chunks│
                    └───────────┬─────────────┘
                                │
   question ──────────────────► ▼
                    ┌─────────────────────────┐
                    │  retrieve               │
                    │  dense + BM25 → RRF     │
                    │  → cross-encoder rerank │
                    └───────────┬─────────────┘
                                │ evidence
                                ▼
                    ┌─────────────────────────┐
                    │  sufficiency_agent      │◄──────┐
                    │  tools: search_code,    │       │
                    │         search_docs     │       │ rewritten query
                    │  "is this enough?"      │───────┘ (max N hops)
                    └───────────┬─────────────┘
                                │
                 ┌──────────────┴──────────────┐
        enough   │                             │  exhausted hops,
        evidence ▼                             ▼  still insufficient
        ┌─────────────────────┐      ┌─────────────────────┐
        │  synthesize         │      │  abstain            │
        │  answer + citations │      │  "not covered"      │
        └──────────┬──────────┘      └─────────────────────┘
                   │
                   ▼
        ┌─────────────────────┐
        │  critique           │
        │  verify every cite  │
        └──────────┬──────────┘
                   │
                   ▼
                answer
```

**The loop is the whole point.** A standard RAG pipeline runs `retrieve → synthesize` and
stops. Here the agent can look at what it has, notice a gap, and go back for more. That
loop is what makes "agentic" an honest description rather than a resume word.

### Finalised node structure

**1. `decompose` — the only node that plans**
- Reads: original question, `human_feedback` (if any), prior hop's evidence, hop counter
- **Hop 1:** scans the question for unfamiliar/domain-specific terms (absorbs the old `domain_identifier` job — no separate node). If terms are unfamiliar, round-1 sub-questions ARE literal term lookups, not real decomposition
- **Hop 2+:** now grounded in vocabulary, decomposes for real into an enumerated checklist of what must be found. Relational questions get the fixed 6-point checklist (what is A, what is B, where they touch, direction/cardinality, where enforced, what on violation)
- **On HITL feedback:** folds human guidance into the next checklist as additional/corrected search targets
- Holds no tool. Emits queries only — never retrieves

**2. `searcher` — pure executor, zero judgment**
- Sole holder of `search_tool` (hybrid: dense `voyage-code-3` + BM25 sparse → RRF fusion → Voyage `rerank-2.5` → top ~5)
- Runs whatever `decompose` handed it. Makes no decision about what to search or when to stop
- This is why it's a node, not an agent — no judgment lives here

**3. `coverage_check` — relevance gate, pre-synthesis**
- Maps retrieved evidence against `decompose`'s checklist, item by item
- Output is only `sufficient` / `insufficient`. Nothing about hop counts, nothing about citations
- Sufficiency is arithmetic coverage of the checklist, not an LLM opinion on "is this enough?" — that's the fix for model over-agreement

**4. Hop-cap check — plain Python conditional edge, not an LLM**
- Reads verdict + hop counter together
- `sufficient` → `response`
- `insufficient` + hops remain → `decompose` (counter++)
- `insufficient` + cap hit → `response`, flagged `exhausted`
- Being code, not a prompt, is what actually kills the infinite-loop risk

**5. `response` — synthesis or refusal**
- `sufficient` → cited answer, forwards to `citation_check`
- `exhausted` → explicit abstention → *Not covered*, skips `citation_check` entirely (nothing to verify in a refusal)

**6. `citation_check` — faithfulness gate, post-synthesis, toolless**
- Verifies each claim actually appears in the chunk it cites — distinct from `coverage_check`'s relevance job
- Fail once → back to `response` only (evidence was fine, synthesis wasn't), one bounded retry
- Fail twice → *Not covered*, tagged `citation_verification_failed` — a different signal from evidence-exhausted, so eval can separate the two failure modes

**7. HITL — blocking gate**
- Entered after `citation_check` passes, or after an exhausted abstention (human can challenge a wrong "Not covered")
- **Approve** → END
- **Reject, no feedback** → terminal, tagged `rejected_no_feedback` — no loop, there's no new signal to act on
- **Reject + feedback** → `decompose`, feedback injected into state
- Bypassed in eval/CI mode — no human present, so it auto-approves or the run never terminates

### State fields that make it work
- `hop_count` + `hop_cap` — automatic loop bound
- `human_retry_count` + cap of 1–2 — separate counter, else a rejected already-exhausted answer loops straight back to exhausted
- `human_feedback` — read by `decompose`, cleared after use
- `checklist` + `coverage_map` — what makes false-confidence rate measurable in Step 11
- `termination_reason` — `approved` / `exhausted` / `citation_verification_failed` / `rejected_no_feedback`

### Loop edges — exactly three, all bounded
- `coverage_check` → `decompose` (hop cap)
- `citation_check` → `response` (1 retry)
- HITL → `decompose` (human cap)

---

## 4. Time budget

**Total: 27 hours across 12 days.**

| Step | Hours | Running total |
|---|---|---|
| 1. Problem and scope | 0.5 | 0.5 |
| 2. Architecture design | 1.0 | 1.5 |
| 3. Environment setup | 1.5 | 3.0 |
| 4. Corpus ingestion | 3.0 | 6.0 |
| 5. Hybrid retrieval + reranking | 3.0 | 9.0 |
| 6. Golden dataset | 2.0 | 11.0 |
| 7. Baseline retrieval eval | 1.5 | 12.5 |
| 8. Agent layer (8a–8f) | 5.0 | 17.5 |
| 9. Synthesis and critique | 2.0 | 19.5 |
| 10. Reliability | 0.5 | 20.0 |
| 11. Full eval harness | 3.0 | 23.0 |
| 12. Observability | 1.5 | 24.5 |
| 13. Serving layer | 0.5 | 25.0 |
| 14. MCP server | 1.5 | 26.5 |
| 15. Package, docs, demo | 2.0 | 28.5 |

Slightly over 27 — that's intentional slack absorption, not a miscalculation. Steps 10 and
13 are the ones to compress if you're behind.

### Calendar mapping

| When | Hours available | Deliverable — concrete, not a topic |
|---|---|---|
| **Tue Sep 1 (eve)** | 2 | Steps 1–2 done: README problem statement written, target repo chosen, graph drawn |
| **Wed Sep 2 (eve)** | 2 | Step 3 done: `docker-compose up` brings Qdrant online, collection created |
| **Thu Sep 3 (eve)** | 2 | Start step 4 — **and pre-assign the weekend in writing** |
| **Sat Sep 5** | ~6 | Step 4 complete: full repo ingested and indexed with metadata |
| **Sun Sep 6** | ~5 | Step 5 complete: hybrid + rerank working, visibly better than dense-only |
| **Mon Sep 7 (eve)** | 2 | Step 6: golden set written (30 questions, labelled) |
| **Tue Sep 8 (eve)** | 2 | Step 7: baseline numbers recorded. Then start 8a |
| **Wed Sep 9 (eve)** | 2 | Steps 8a–8b: graph + tools wired, single pass runs, grounding works |
| **Thu Sep 10 (eve)** | 2 | Steps 8c–8d: classifier + decomposition producing real checklists |
| **Fri Sep 11 (eve)** | 2 | Steps 8e–8f + 9: coverage mapping, loop control, synthesis and critique |
| **Sat Sep 12** | ~6 | Steps 11–12: full eval harness in CI + both tracing stacks |
| **Sun Sep 13** | ~5 | Steps 13–15: FastAPI, MCP server, docker-compose, README, demo recorded |

**Total allocated: ~27.5 hours.** Your actual availability across these 12 days is roughly
50+ hours, so the plan uses about half of it. That slack exists specifically because your
documented failure mode is weekend collapse — the schedule survives losing one weekend day,
but not both.

### The two dates that matter most

- **Thu Sep 3** — pre-assign Sep 5–6 in writing, as deliverables, not topics. This is the
  mitigation for the pattern that killed the last three attempts.
- **Sun Sep 6** — if hybrid retrieval isn't working by end of day, everything downstream
  compresses. This is the real checkpoint, not the ship date.
#   C a p s t o n e - 1  
 