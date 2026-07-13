import json
import time
import uuid

import chromadb

from app.core.config import settings
from app.services.embedder import embed


def _get_collection() -> chromadb.Collection:
    client = chromadb.PersistentClient(path=settings.chroma_path)
    return client.get_or_create_collection(
        name=settings.cache_collection,
        metadata={"hnsw:space": "cosine"},
    )


async def cache_lookup(query: str, ttl_override: int | None = None) -> dict | None:
    """Return cached result if a semantically similar recent query exists."""
    ttl = ttl_override if ttl_override is not None else settings.cache_ttl_seconds
    if ttl == 0:
        return None  # temporal queries always bypass cache

    embedding = await embed(query)
    collection = _get_collection()

    try:
        results = collection.query(
            query_embeddings=[embedding],
            n_results=1,
            where={"timestamp": {"$gt": time.time() - ttl}},
            include=["documents", "distances", "metadatas"],
        )
    except Exception:
        return None

    if not results["ids"] or not results["ids"][0]:
        return None

    distance = results["distances"][0][0]
    if distance > settings.cache_similarity_threshold:
        return None

    raw = results["documents"][0][0]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


async def cache_store(query: str, result: dict) -> None:
    """Store answer + citations + page_extracts keyed by query embedding."""
    embedding = await embed(query)
    collection = _get_collection()

    collection.upsert(
        ids=[str(uuid.uuid4())],
        embeddings=[embedding],
        documents=[json.dumps(result)],
        metadatas=[{"query": query, "timestamp": time.time()}],
    )
