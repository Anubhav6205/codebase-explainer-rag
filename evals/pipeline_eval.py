from dotenv import load_dotenv

load_dotenv()

import argparse
import json
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from graph.graph import app
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import faithfulness, context_precision, context_recall
from langchain_openai import ChatOpenAI
from langchain.messages import HumanMessage, SystemMessage

GOLDEN_PATH = os.path.join(os.path.dirname(__file__), "golden.json")
JOBS_DIR = os.path.join(os.path.dirname(__file__), "jobs")
MAX_WORKERS = 5

with open(GOLDEN_PATH, "r") as f:
    golden_data = json.load(f)

judge_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

JUDGE_SYS = SystemMessage(content="""\
You are an answer quality judge for a codebase Q&A system. Given a question,
a reference answer, and the system's answer, score the system's answer on two
dimensions. Return a JSON object with exactly these fields:
  "answer_quality": integer 1-5 (1=wrong/irrelevant, 3=partially correct, 5=complete and accurate)
  "citation_quality": integer 1-5 (1=no citations, 3=some claims cited, 5=every factual claim has a specific file citation)
  "reasoning": one short sentence explaining the scores

Return only the JSON object, nothing else.
""")


def judge_answer(question, reference, answer, citations):
    if not answer or not reference:
        return {"answer_quality": 0, "citation_quality": 0, "reasoning": "skipped"}
    citations_str = "\n".join(
        f"- {c.get('claim','')[:80]} -> {c.get('chunk_ids', [])}"
        for c in (citations or [])[:5]
    )
    context = (
        f"Question: {question}\n\n"
        f"Reference answer: {reference}\n\n"
        f"System answer: {answer[:1000]}\n\n"
        f"Citations (sample):\n{citations_str or '(none)'}"
    )
    try:
        result = judge_llm.invoke([JUDGE_SYS, HumanMessage(content=context)])
        return json.loads(result.content)
    except Exception as e:
        return {"answer_quality": 0, "citation_quality": 0, "reasoning": f"error: {e}"}


def run_question(item):
    qid = item["id"]
    question = item["question"]
    ground_truth = item.get("answer")

    thread_id = str(uuid.uuid4())
    try:
        result = app.invoke(
            {"question": question},
            config={"configurable": {"thread_id": thread_id}},
        )
        answer = result.get("answer", "")
        termination_reason = result.get("termination_reason", "")
        retrieved_chunks = result.get("retrieved_chunks", [])
        citations = result.get("citations", [])
        contexts = [c["text"] for c in retrieved_chunks]
        error = None
    except Exception as e:
        print(f"[{qid}] ERROR: {e}")
        answer = ""
        termination_reason = "eval_error"
        contexts = []
        citations = []
        error = str(e)

    print(f"[{qid}] termination_reason={termination_reason!r} answer_len={len(answer)} chunks={len(contexts)}")
    return {
        "id": qid,
        "type": item["type"],
        "question": question,
        "ground_truth": ground_truth,
        "answer": answer,
        "citations": citations,
        "termination_reason": termination_reason,
        "contexts": contexts,
        "num_chunks": len(contexts),
        "error": error,
    }


def run_graph_phase():
    print(f"=== GRAPH PHASE (parallel workers={MAX_WORKERS}) ===")
    questions = golden_data["questions"]
    total = len(questions)
    raw_results = [None] * total

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_idx = {
            executor.submit(run_question, item): i
            for i, item in enumerate(questions)
        }
        completed = 0
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            raw_results[idx] = future.result()
            completed += 1
            print(f"  [{completed}/{total}] {raw_results[idx]['id']} done")

    os.makedirs(JOBS_DIR, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    checkpoint_path = os.path.join(JOBS_DIR, f"checkpoint_{timestamp}.json")
    with open(checkpoint_path, "w", encoding="utf-8") as f:
        json.dump(raw_results, f, indent=2, ensure_ascii=False)
    print(f"\nCheckpoint saved -> {checkpoint_path}")
    return raw_results, checkpoint_path


def run_llm_judge_phase(raw_results):
    print("\n=== LLM-AS-JUDGE PHASE ===")
    q_answered = [
        r for r in raw_results
        if r["id"].startswith("Q") and r["termination_reason"] not in ("exhausted", "eval_error")
    ]
    scores = []
    for r in q_answered:
        score = judge_answer(r["question"], r["ground_truth"], r["answer"], r.get("citations", []))
        score["id"] = r["id"]
        print(f"  [{r['id']}] answer_quality={score.get('answer_quality')} citation_quality={score.get('citation_quality')}")
        scores.append(score)

    aq_vals = [s["answer_quality"] for s in scores if s.get("answer_quality")]
    cq_vals = [s["citation_quality"] for s in scores if s.get("citation_quality")]
    aggregate = {
        "avg_answer_quality": round(sum(aq_vals) / len(aq_vals), 3) if aq_vals else None,
        "avg_citation_quality": round(sum(cq_vals) / len(cq_vals), 3) if cq_vals else None,
        "n": len(scores),
    }
    print(f"LLM-judge aggregate: {aggregate}")
    return scores, aggregate


def run_ragas_phase(raw_results):
    print("\n=== RAGAS PHASE ===")

    u_results = [r for r in raw_results if r["id"].startswith("U")]
    false_confident = [r for r in u_results if r["termination_reason"] != "exhausted"]
    false_confidence_rate = len(false_confident) / len(u_results) if u_results else 0
    print(f"False-confidence rate: {len(false_confident)}/{len(u_results)} = {false_confidence_rate:.2f}")

    q_results = [r for r in raw_results if r["id"].startswith("Q")]
    answered = [r for r in q_results if r["termination_reason"] not in ("exhausted", "eval_error")]
    coverage_failures = [r for r in q_results if r["termination_reason"] == "exhausted"]
    print(f"Q answered: {len(answered)}/{len(q_results)} | coverage failures: {len(coverage_failures)}")

    ragas_scores = []
    ragas_aggregate = {}
    if answered:
        dataset = Dataset.from_dict(
            {
                "user_input": [r["question"] for r in answered],
                "retrieved_contexts": [r["contexts"] for r in answered],
                "response": [r["answer"] for r in answered],
                "reference": [r["ground_truth"] for r in answered],
            }
        )

        evaluator_llm = ChatOpenAI(model="gpt-4o-mini")
        print("Running Ragas evaluation...")
        ragas_result = evaluate(
            dataset=dataset,
            llm=evaluator_llm,
            metrics=[faithfulness, context_precision, context_recall],
        )
        df = ragas_result.to_pandas()
        ragas_scores = df.to_dict(orient="records")
        ragas_aggregate = {
            "faithfulness": float(df["faithfulness"].mean()),
            "context_precision": float(df["context_precision"].mean()),
            "context_recall": float(df["context_recall"].mean()),
        }
        print(f"Ragas aggregate: {ragas_aggregate}")

    return {
        "u_results": u_results,
        "false_confident": false_confident,
        "false_confidence_rate": false_confidence_rate,
        "answered": answered,
        "coverage_failures": coverage_failures,
        "ragas_scores": ragas_scores,
        "ragas_aggregate": ragas_aggregate,
    }


def save_output(raw_results, ragas_data, judge_scores, judge_aggregate, checkpoint_path=None):
    os.makedirs(JOBS_DIR, exist_ok=True)
    unique_id = uuid.uuid4()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    file_path = os.path.join(JOBS_DIR, f"pipeline_eval_{unique_id}_{timestamp}.json")

    # Step 7 baseline for comparison
    baseline = {
        "context_precision": 0.9816,
        "context_recall": 0.6905,
    }

    output = {
        "timestamp": timestamp,
        "checkpoint_used": checkpoint_path,
        "summary": {
            "total_questions": len(raw_results),
            "q_answered": len(ragas_data["answered"]),
            "q_coverage_failures": len(ragas_data["coverage_failures"]),
            "u_total": len(ragas_data["u_results"]),
            "false_confident_count": len(ragas_data["false_confident"]),
            "false_confidence_rate": round(ragas_data["false_confidence_rate"], 4),
        },
        "ragas_aggregate": ragas_data["ragas_aggregate"],
        "llm_judge_aggregate": judge_aggregate,
        "baseline_comparison": {
            "step7_retriever_only": baseline,
            "step11_full_pipeline": {
                "context_precision": ragas_data["ragas_aggregate"].get("context_precision"),
                "context_recall": ragas_data["ragas_aggregate"].get("context_recall"),
                "faithfulness": ragas_data["ragas_aggregate"].get("faithfulness"),
            },
            "delta": {
                "context_precision": round(
                    (ragas_data["ragas_aggregate"].get("context_precision") or 0) - baseline["context_precision"], 4
                ),
                "context_recall": round(
                    (ragas_data["ragas_aggregate"].get("context_recall") or 0) - baseline["context_recall"], 4
                ),
            },
        },
        "ragas_per_question": ragas_data["ragas_scores"],
        "llm_judge_per_question": judge_scores,
        "false_confident_questions": [r["id"] for r in ragas_data["false_confident"]],
        "coverage_failure_questions": [r["id"] for r in ragas_data["coverage_failures"]],
        "raw_results": raw_results,
    }

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=4, ensure_ascii=False)
    print(f"\nResults saved -> {file_path}")
    return file_path


def run_pipeline_eval(checkpoint_path=None):
    if checkpoint_path:
        print(f"=== RESUMING FROM CHECKPOINT: {checkpoint_path} ===")
        with open(checkpoint_path, "r", encoding="utf-8") as f:
            raw_results = json.load(f)
    else:
        raw_results, checkpoint_path = run_graph_phase()

    ragas_data = run_ragas_phase(raw_results)
    judge_scores, judge_aggregate = run_llm_judge_phase(raw_results)
    save_output(raw_results, ragas_data, judge_scores, judge_aggregate, checkpoint_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=str, default=None, help="Path to checkpoint JSON to skip graph phase")
    args = parser.parse_args()
    run_pipeline_eval(checkpoint_path=args.checkpoint)
