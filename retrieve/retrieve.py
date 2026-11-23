import os
from qdrant_client import QdrantClient, models
import voyageai
from fastembed import SparseTextEmbedding
from dotenv import load_dotenv

load_dotenv()


qdrant_secret = os.getenv("QDRANT_API_KEY")
quadrant_client = QdrantClient(
    url=os.getenv("QDRANT_URL"),
    api_key=qdrant_secret,
)
voyage_secret = os.getenv("VOYAGE_API_KEY")
vo = voyageai.Client(api_key=voyage_secret)

sparse_model = SparseTextEmbedding(model_name="Qdrant/bm25")


def dense_search(query: str, collection_name: str, top_k=25):
    query_vector = vo.embed(
        [query], model="voyage-code-3", input_type="query"
    ).embeddings[0]
    search_results = quadrant_client.query_points(
        collection_name=collection_name, query=query_vector, limit=top_k
    )
    return search_results


def sparse_search(query: str, collection_name: str, top_k=25):
    query_embedding = next(sparse_model.query_embed(query))
    search_results = quadrant_client.query_points(
        collection_name=collection_name,
        query=models.SparseVector(
            indices=query_embedding.indices.tolist(),
            values=query_embedding.values.tolist(),
        ),
        using="sparse",
        limit=top_k,
    )
    return search_results


def preview_text(text: str, length: int = 120) -> str:
    end_of_license = text.find("*/")
    if end_of_license != -1:
        snippet = text[end_of_license + 2 : end_of_license + 2 + length].strip()
    else:
        snippet = text[:length]
    return snippet.replace("\n", " ")


def print_results(label: str, results, collection_type: str = "logic"):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    for i, p in enumerate(results.points, 1):
        text = p.payload.get("text", "")
        if collection_type == "docs":
            h1 = p.payload.get("Header 1", "")
            h2 = p.payload.get("Header 2", "")
            h3 = p.payload.get("Header 3", "")
            headers = " > ".join(x for x in [h1, h2, h3] if x)
            snippet = text.replace("\n", " ")
            print(f"  [{i:2}] id={p.id:<5} score={p.score:.4f} | {headers or snippet}")
        else:
            snippet = preview_text(text)
            print(f"  [{i:2}] id={p.id:<5} score={p.score:.4f} | {snippet}")
    print()


def print_fused_results(label: str, fused_results):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    for i, (pid, data) in enumerate(fused_results, 1):
        text = data["payload"].get("text", "")
        score = data["score"]
        snippet = preview_text(text)
        print(f"  [{i:2}] id={pid:<5} rrf_score={score:.6f} | {snippet}")
    print()


def reciprocal_rank_fusion(results_list, k=60):
    scores = {}
    for result in results_list:
        for rank, point in enumerate(result.points):
            pid = point.id
            if pid not in scores:
                scores[pid] = {"score": 0, "payload": point.payload}
            scores[pid]["score"] += 1 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1]["score"], reverse=True)


def print_reranked_results(label: str, reranked_results):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    for i, (pid, data, score) in enumerate(reranked_results, 1):
        text = data["payload"].get("text", "")
        snippet = preview_text(text)
        print(f"  [{i:2}] id={pid:<5} rerank_score={score:.4f} | {snippet}")
    print()


def rerank(query: str, fused_results, top_n=10):
    texts = [data["payload"]["text"] for _, data in fused_results]
    result = vo.rerank(query=query, documents=texts, model="rerank-2", top_k=top_n)
    return [
        (fused_results[r.index][0], fused_results[r.index][1], r.relevance_score)
        for r in result.results
    ]

def retrieve_reranked(query):
    docs_dense_results = dense_search(query, "dense_docs", top_k=25)
    # print_results("DOCS — dense_docs", docs_results, collection_type="docs")

    logic_dense_results = dense_search(query, "dense_logic", top_k=25)
    # print_results("LOGIC — dense_logic", logic_results, collection_type="logic")

    docs_sparse_results = sparse_search(query, "sparse_docs", top_k=25)

    logic_sparse_results = sparse_search(query, "sparse_logic", top_k=25)

    fused_results = reciprocal_rank_fusion(
        [
            docs_dense_results,
            logic_dense_results,
            docs_sparse_results,
            logic_sparse_results,
        ]
    )
    reranked = rerank(query, fused_results)
    return reranked


if __name__ == "__main__":
    query_text = (
        "My catalog-info.yaml has no namespace field at all, but the entity shows up as "
        "default/component/my-service. Where does the string 'default' come from — is it "
        "hardcoded in ten places? And is the resulting namespace actually validated, or just "
        "silently added?"
    )

    docs_dense_results = dense_search(query_text, "dense_docs", top_k=25)
    # print_results("DOCS — dense_docs", docs_results, collection_type="docs")

    logic_dense_results = dense_search(query_text, "dense_logic", top_k=25)
    # print_results("LOGIC — dense_logic", logic_results, collection_type="logic")

    docs_sparse_results = sparse_search(query_text, "sparse_docs", top_k=25)

    logic_sparse_results = sparse_search(query_text, "sparse_logic", top_k=25)

    fused_results = reciprocal_rank_fusion(
        [
            docs_dense_results,
            logic_dense_results,
            docs_sparse_results,
            logic_sparse_results,
        ]
    )
    reranked = rerank(query_text, fused_results)
    # print_reranked_results("RERANKED — voyage-rerank-2", reranked)
