"""Documents — upload R2, extraction, RAG, résumé."""

import os
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, UploadFile

from core.deps import get_current_user_id
from core.database import get_supabase_admin
from core.responses import error_response, success_response
from models.document import DocumentAskRequest, DocumentSummarizeRequest
from services import ai_router, ocr_service, storage_service, vector_service
from services.usage_service import log_usage

router = APIRouter(prefix="/documents", tags=["documents"])

MAX_BYTES = 10 * 1024 * 1024


def _db():
    return get_supabase_admin()


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
):
    """Upload fichier, extraction texte, embeddings, métadonnées."""
    raw = await file.read()
    if len(raw) > MAX_BYTES:
        return error_response("Fichier trop volumineux (max 10 Mo)", 400)
    fname = file.filename or "document.bin"
    ct = file.content_type or "application/octet-stream"
    doc_id = str(uuid.uuid4())
    try:
        text, pages = await ocr_service.extract_document_text(raw, fname, ct)
    except Exception as e:
        return error_response(f"Extraction impossible: {e}", 400)
    key, url = await storage_service.upload_bytes(raw, f"docs/{user_id}", fname, ct)
    ext = (os.path.splitext(fname)[1] or "").lower().lstrip(".")
    file_type = ext if ext in ("pdf", "docx", "xlsx", "png", "jpg", "jpeg", "webp", "gif") else "other"
    if file_type in ("png", "jpg", "jpeg", "webp", "gif"):
        file_type = "image"
    chunks = vector_service.chunk_text(text)
    await vector_service.upsert_document_chunks(doc_id, user_id, chunks)
    c = _db()
    if c:
        try:
            c.table("documents").insert(
                {
                    "id": doc_id,
                    "user_id": user_id,
                    "filename": fname,
                    "file_type": file_type,
                    "file_size": len(raw),
                    "storage_path": key,
                    "extracted_text": text[:50000],
                    "page_count": pages,
                    "embedding_id": doc_id,
                },
            ).execute()
        except Exception:
            pass
    preview = text[:800].replace("\n", " ")
    await log_usage(user_id, "/documents/upload", None, "documents")
    return success_response(
        {
            "doc_id": doc_id,
            "filename": fname,
            "page_count": pages,
            "preview_text": preview,
            "storage_key": key,
        },
        "Document indexé",
    )


@router.post("/ask")
async def ask_document(body: DocumentAskRequest, user_id: str = Depends(get_current_user_id)):
    """Q&R RAG sur un document."""
    c = _db()
    if c:
        try:
            row = (
                c.table("documents")
                .select("user_id,extracted_text")
                .eq("id", body.doc_id)
                .single()
                .execute()
            )
            if not row.data or row.data.get("user_id") != user_id:
                return error_response("Document introuvable", 404)
        except Exception:
            return error_response("Document introuvable", 404)
    try:
        ctx = await vector_service.query_relevant_chunks(user_id, body.doc_id, body.question, 6)
    except Exception:
        ctx = []
    if not ctx and c:
        try:
            full = (
                c.table("documents")
                .select("extracted_text")
                .eq("id", body.doc_id)
                .eq("user_id", user_id)
                .single()
                .execute()
            )
            blob = (full.data or {}).get("extracted_text") or ""
            ctx = [blob[:12000]]
        except Exception:
            ctx = []
    context_block = "\n---\n".join(ctx)[:14000]
    prompt = (
        f"Contexte document :\n{context_block}\n\nQuestion : {body.question}\n"
        "Réponds en t'appuyant sur le contexte. Si tu ne sais pas, dis-le."
    )
    try:
        answer, model, tok = await ai_router.run_chat(prompt, [], "auto", "auto", None, False, False)
    except Exception as e:
        return error_response(str(e), 500)
    await log_usage(user_id, "/documents/ask", tok, model)
    return success_response(
        {
            "answer": answer,
            "sources": [f"chunk:{i}" for i in range(len(ctx))],
            "confidence": 0.85 if ctx else 0.4,
        },
        "OK",
    )


@router.post("/summarize")
async def summarize_document(
    body: DocumentSummarizeRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Résumé structuré (puces, paragraphe, points clés)."""
    c = _db()
    text = ""
    if c:
        try:
            row = (
                c.table("documents")
                .select("extracted_text")
                .eq("id", body.doc_id)
                .eq("user_id", user_id)
                .single()
                .execute()
            )
            text = (row.data or {}).get("extracted_text") or ""
        except Exception:
            text = ""
    if not text.strip():
        return error_response("Texte document introuvable", 404)
    fmt = body.format
    instructions = {
        "bullets": "Résume en puces claires (5 à 12 puces).",
        "paragraph": "Résume en un ou deux paragraphes fluides.",
        "key_points": "Liste les points clés numérotés (1., 2., ...).",
    }.get(fmt, "Résume en puces.")
    prompt = f"{instructions}\n\nDocument :\n{text[:20000]}"
    try:
        summary, model, tok = await ai_router.run_chat(prompt, [], "auto", "auto", None, False, False)
    except Exception as e:
        return error_response(str(e), 500)
    await log_usage(user_id, "/documents/summarize", tok, model)
    return success_response({"summary": summary, "format": fmt}, "OK")
