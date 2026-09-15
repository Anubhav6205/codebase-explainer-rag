from dotenv import load_dotenv

load_dotenv()

import json
import sys
import os
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from retrieve.retrieve import retrieve_reranked

from datasets import Dataset
from ragas import evaluate
from ragas.metrics import context_precision, context_recall
from langchain_openai import ChatOpenAI

with open("golden.json", "r") as file:
    golden_data = json.load(file)


if __name__ == "__main__":
    print("--BASELINE--")

    # retrieval_results = retrieve_reranked()

    filtered_golden_data = [
        data for data in golden_data["questions"] if "Q" in data["id"]
    ]

    user_inputs = []
    references = []
    all_retrieved_contexts = []

    for data in filtered_golden_data:
        user_input = data["question"]
        reference = data["answer"]
        reranked = retrieve_reranked(user_input)
        contexts = [item[1]["payload"]["text"] for item in reranked]

        user_inputs.append(user_input)
        references.append(reference)
        all_retrieved_contexts.append(contexts)

    evaluation_dataset = Dataset.from_dict(
        {
            "user_input": user_inputs,
            "retrieved_contexts": all_retrieved_contexts,
            "reference": references,
        }
    )

    evaluator_llm = ChatOpenAI(model="gpt-4o-mini")
    print("Running RAGAS Evaluation...")
    results = evaluate(
        dataset=evaluation_dataset,
        llm=evaluator_llm,
        metrics=[context_precision, context_recall],
    )

    unique_id = uuid.uuid4()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    jobs_dir = os.path.join(os.path.dirname(__file__), "jobs")
    os.makedirs(jobs_dir, exist_ok=True)
    file_path = os.path.join(jobs_dir, f"job_{unique_id}_{timestamp}.json")
    with open(file_path, "w", encoding="utf-8") as json_file:
        json.dump(results.to_pandas().to_dict(orient="records"), json_file, indent=4)
    print(f"Results saved to {file_path}")
