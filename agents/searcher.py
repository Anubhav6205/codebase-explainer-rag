import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from state import MessageState
from retrieve.retrieve import retrieve_reranked
from state import Chunk


def searcher_agent(state: MessageState):
    hop_count_in = state.get("hop_count", 0)
    current_decompose_queries = state.get("current_decompose_queries", [])
    print(f"[searcher] ENTER hop={hop_count_in} queries_this_hop={len(current_decompose_queries)}")

    chunks = []
    for i, query in enumerate(current_decompose_queries):
        try:
            current_chunk = retrieve_reranked(query)
        except Exception as e:
            print(f"[searcher] retrieve_reranked FAILED for query={query}")
            current_chunk = []
        print(f"[searcher] query {i+1}/{len(current_decompose_queries)}: {query!r} -> retrieved {len(current_chunk)} tuples")

        # Transform: (pid, {score, payload}, rerank_score) tuples -> Chunk dicts
        if current_chunk:
            first_pid, first_data, first_score = current_chunk[0]
            print(f"[searcher] transform tuple -> Chunk (sample) | before: (pid={first_pid}, rerank_score={first_score:.3f}, payload_keys={list(first_data['payload'].keys())[:4]}) | after: Chunk(id={first_pid}, source_file={first_data['payload'].get('source_file')!r}, text_len={len(first_data['payload'].get('text', ''))})")

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

    # Transform: raw chunks -> deduped chunks
    existing_ids = {c["id"] for c in state.get("retrieved_chunks", [])}
    seen = set()
    deduped = []
    for c in chunks:
        if c["id"] in existing_ids or c["id"] in seen:
            continue
        seen.add(c["id"])
        deduped.append(c)
    print(f"[searcher] transform chunks(list) -> deduped(list) | before: raw={len(chunks)} (existing_in_state={len(existing_ids)}) | after: deduped={len(deduped)}")

    print(f"[searcher] EXIT hop_count->{hop_count_in + 1} chunks_added={len(deduped)}")
    return {
        "retrieved_chunks": deduped,
        "chunks_added_this_hop": len(deduped),
        "current_decompose_queries": [],
        "hop_count": state.get("hop_count", 0) + 1,
    }
