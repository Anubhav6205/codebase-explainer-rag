import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from state import MessageState
from retrieve import retrieve_reranked
from state import Chunk


def searcher_agent(state: MessageState):
    current_decompose_queries = state.get("current_decompose_queries",[])
    chunks = []
    for query in current_decompose_queries:
        current_chunk = retrieve_reranked(query)
        chunks.extend(
            Chunk(
                id=pid,
                text=data["payload"].get("text", ""),
                score=rerank_score,
                source_file=data["payload"].get("source_file"),
                headers=" > ".join(
                    h
                    for h in (
                        data["payload"].get("Header 1"),
                        data["payload"].get("Header 2"),
                        data["payload"].get("Header 3"),
                    )
                    if h
                )
                or None,
                query=query,
            )
            for pid, data, rerank_score in current_chunk
        )

    existing_ids = {c["id"] for c in state.get("retrieved_chunks", [])}
    seen = set()
    deduped = []
    for c in chunks:
        if c["id"] in existing_ids or c["id"] in seen:
            continue
        seen.add(c["id"])
        deduped.append(c)

    return {
        "retrieved_chunks": deduped,
        "current_decompose_queries": [],
        "hop_count": state.get("hop_count", 0) + 1,
    }
