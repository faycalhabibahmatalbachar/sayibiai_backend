"""Embeddings et RAG — Pinecone + fallback mémoire locale (dev)."""

import hashlib
from typing import Any, Dict, List, Optional

import httpx

from core.config import get_settings

# Cache mémoire processus si Pinecone indisponible
_memory_chunks: Dict[str, List[Dict[str, Any]]] = {}


async def _embed_texts_openai_compatible(texts: List[str], provider: str = "groq") -> List[List[float]]:
    """
    Embeddings via API compatible OpenAI (Groq n'expose pas d'embeddings ;
    on utilise l'API voyage ou sentence via HTTP si besoin).
    Pour le MVP, embedding simplifié : hash vectoriel faible dimension OU Mistral embeddings.
    """
    settings = get_settings()
    # Mistral embeddings API
    if settings.mistral_api_key:
        url = "https://api.mistral.ai/v1/embeddings"
        headers = {
            "Authorization": f"Bearer {settings.mistral_api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": "mistral-embed", "input": texts}
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
        return [item["embedding"] for item in data["data"]]
    # Repli : vecteur pseudo (non optimal mais évite crash sans clés)
    out: List[List[float]] = []
    for t in texts:
        h = hashlib.sha256(t.encode("utf-8")).digest()
        vec = [((h[i % 32] + h[(i + 1) % 32]) / 510.0) - 0.5 for i in range(64)]
        out.append(vec)
    return out


def _pinecone_index():
    settings = get_settings()
    if not settings.pinecone_api_key:
        return None
    try:
        from pinecone import Pinecone

        pc = Pinecone(api_key=settings.pinecone_api_key)
        name = settings.pinecone_index
        return pc.Index(name)
    except Exception:
        return None


async def upsert_document_chunks(
    doc_id: str,
    user_id: str,
    chunks: List[str],
    metadata_prefix: Optional[Dict[str, Any]] = None,
) -> None:
    """Découpe déjà faite : upsert chaque chunk avec id stable."""
    if not chunks:
        return
    settings = get_settings()
    embeddings = await _embed_texts_openai_compatible(chunks)
    meta_base = {"doc_id": doc_id, "user_id": user_id}
    if metadata_prefix:
        meta_base.update(metadata_prefix)
    index = _pinecone_index()
    vectors: List[Dict[str, Any]] = []
    for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        vid = f"{user_id}-{doc_id}-{i}"
        vectors.append(
            {
                "id": vid,
                "values": emb,
                "metadata": {**meta_base, "chunk_index": i, "text": chunk[:1000]},
            }
        )
    # Index Pinecone : dimension alignée sur les embeddings Mistral uniquement
    if index and settings.mistral_api_key:
        import asyncio

        await asyncio.to_thread(
            lambda: index.upsert(vectors=vectors),
        )
        return
    # Fallback mémoire
    key = f"{user_id}:{doc_id}"
    _memory_chunks[key] = [
        {"id": v["id"], "embedding": embeddings[i], "text": chunks[i]}
        for i, v in enumerate(vectors)
    ]


def _cosine_sim(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def query_relevant_chunks(
    user_id: str,
    doc_id: str,
    question: str,
    top_k: int = 5,
) -> List[str]:
    """Récupère les passages les plus pertinents pour une question."""
    settings = get_settings()
    q_emb = (await _embed_texts_openai_compatible([question]))[0]
    index = _pinecone_index()
    if index and settings.mistral_api_key:
        import asyncio

        def _q():
            return index.query(
                vector=q_emb,
                top_k=top_k,
                include_metadata=True,
                filter={"user_id": {"$eq": user_id}, "doc_id": {"$eq": doc_id}},
            )

        res = await asyncio.to_thread(_q)
        matches = getattr(res, "matches", None) or (res.get("matches") if isinstance(res, dict) else None) or []
        texts: List[str] = []
        for m in matches:
            meta = getattr(m, "metadata", None) or (m.get("metadata") if isinstance(m, dict) else {}) or {}
            t = meta.get("text") if isinstance(meta, dict) else None
            if t:
                texts.append(str(t))
        return texts

    key = f"{user_id}:{doc_id}"
    stored = _memory_chunks.get(key) or []
    scored: List[tuple[float, str]] = []
    for item in stored:
        sim = _cosine_sim(q_emb, item["embedding"])
        scored.append((sim, item["text"]))
    scored.sort(key=lambda x: -x[0])
    return [t for _, t in scored[:top_k]]


def chunk_text(text: str, max_chars: int = 1200) -> List[str]:
    """Découpe un long texte en morceaux avec recouvrement léger."""
    text = text.strip()
    if not text:
        return []
    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunk = text[start:end]
        chunks.append(chunk)
        if end == len(text):
            break
        start = end - 200
        if start < 0:
            start = end
    return chunks
