"""Phase 3 — embed chunks with OpenAI text-embedding-3-small and store in Chroma (persisted).

We compute embeddings ourselves (not via Chroma's default embedder) so the same model is used
for chunks and queries. Cosine space so distances map cleanly to a normalized similarity for
the refusal threshold (similarity = 1 - distance).
"""

import json
import sys
from pathlib import Path

import chromadb
from openai import OpenAI

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config  # noqa: E402

BATCH = 100


def embed_texts(client: OpenAI, texts: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), BATCH):
        resp = client.embeddings.create(model=config.EMBED_MODEL, input=texts[i:i + BATCH])
        out.extend(d.embedding for d in resp.data)
        print(f"  embedded {min(i + BATCH, len(texts))}/{len(texts)}")
    return out


def main() -> None:
    chunks = json.loads(Path(config.CHUNKS_PATH).read_text())
    print(f"Loaded {len(chunks)} chunks")

    oai = OpenAI()  # reads OPENAI_API_KEY from env (loaded by config)
    embeddings = embed_texts(oai, [c["text"] for c in chunks])

    client = chromadb.PersistentClient(path=config.CHROMA_DIR)
    # Fresh build each run so re-ingest is reproducible (cheap; corpus is small).
    try:
        client.delete_collection(config.COLLECTION)
    except Exception:  # noqa: BLE001 - collection may not exist on first run; that's fine
        pass
    coll = client.create_collection(config.COLLECTION, metadata={"hnsw:space": "cosine"})

    # Chroma metadata values must be scalars (no None) — coerce missing item/section to "".
    metadatas = [{
        "ticker": c["ticker"], "company": c["company"],
        "item": c["item"] or "", "section_title": c["section_title"] or "",
        "accession": c["accession"], "filing_date": c["filing_date"], "kind": c["kind"],
    } for c in chunks]

    for i in range(0, len(chunks), BATCH):
        coll.add(
            ids=[c["chunk_id"] for c in chunks[i:i + BATCH]],
            embeddings=embeddings[i:i + BATCH],
            documents=[c["text"] for c in chunks[i:i + BATCH]],
            metadatas=metadatas[i:i + BATCH],
        )
    print(f"Stored {coll.count()} vectors in Chroma collection '{config.COLLECTION}' at {config.CHROMA_DIR}")


if __name__ == "__main__":
    main()
