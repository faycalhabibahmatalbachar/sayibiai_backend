"""Chat — messages, streaming SSE, historique."""

import json
import uuid
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from core.deps import get_current_user_id
from core.database import get_supabase_admin
from core.responses import error_response, success_response
from models.chat import ChatMessageRequest, ChatStreamRequest
from services import ai_router
from services import search_service
from services.usage_service import log_usage

router = APIRouter(prefix="/chat", tags=["chat"])


def _client():
    return get_supabase_admin()


async def _load_history(session_id: str, user_id: str) -> List[dict]:
    if not session_id:
        return []
    c = _client()
    if not c:
        return []
    try:
        conv = (
            c.table("chat_sessions")
            .select("id")
            .eq("id", session_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not conv.data:
            return []
        res = (
            c.table("messages")
            .select("role,content")
            .eq("session_id", session_id)
            .order("created_at", desc=False)
            .execute()
        )
        return res.data or []
    except Exception:
        return []


async def _ensure_conversation(session_id: Optional[str], user_id: str, title: str) -> str:
    sid = session_id or str(uuid.uuid4())
    c = _client()
    if not c:
        return sid
    try:
        existing = c.table("chat_sessions").select("id").eq("id", sid).execute()
        if not existing.data:
            c.table("chat_sessions").insert(
                {"id": sid, "user_id": user_id, "title": title[:120]},
            ).execute()
    except Exception:
        pass
    return sid


async def _save_message(
    session_id: str,
    role: str,
    content: str,
    tokens: Optional[int],
) -> None:
    c = _client()
    if not c:
        return
    try:
        row: dict = {
            "session_id": session_id,
            "role": role,
            "content": content,
        }
        if tokens is not None:
            row["tokens"] = tokens
        c.table("messages").insert(row).execute()
    except Exception:
        pass


@router.post("/message")
async def post_message(body: ChatMessageRequest, user_id: str = Depends(get_current_user_id)):
    """Message chat classique — routage LLM + persistance."""
    history = await _load_history(body.session_id or "", user_id) if body.session_id else []
    title = body.message[:80]
    session_id = await _ensure_conversation(body.session_id, user_id, title)
    hist = [{"role": m["role"], "content": m["content"]} for m in history]
    try:
        reply, model_used, tokens, extra = await ai_router.run_chat(
            body.message,
            hist,
            body.language,
            body.model_preference,
            body.personality,
            bool(body.expert_mode),
            need_vision=False,
            force_web_search=bool(body.web_search),
            document_id=body.document_id,
            create_mode=bool(body.create_mode),
            create_type=body.create_type,
            user_id=user_id,
        )
    except Exception as e:
        return error_response(str(e), 500)
    await _save_message(session_id, "user", body.message, None)
    await _save_message(session_id, "assistant", reply, tokens)
    await log_usage(user_id, "/chat/message", tokens, model_used)
    payload = {
        "response": reply,
        "model_used": model_used,
        "tokens": tokens,
        "session_id": session_id,
    }
    if extra:
        payload["metadata"] = extra
    return success_response(payload, "OK")


@router.post("/stream")
async def post_stream(body: ChatStreamRequest, user_id: str = Depends(get_current_user_id)):
    """Réponse en flux SSE (texte brut concaténé)."""

    async def event_gen():
        history = await _load_history(body.session_id or "", user_id) if body.session_id else []
        title = body.message[:80]
        session_id = await _ensure_conversation(body.session_id, user_id, title)
        hist = [{"role": m["role"], "content": m["content"]} for m in history]
        full: List[str] = []
        meta_acc: dict = {}
        try:
            if body.web_search:
                try:
                    meta_acc["sources"] = await search_service.web_search(body.message, max_results=6)
                    meta_acc["search_images"] = await search_service.web_image_search(
                        body.message,
                        max_results=8,
                    )
                except Exception:
                    meta_acc.setdefault("sources", [])
                    meta_acc.setdefault("search_images", [])
                yield f"data: {json.dumps({'metadata': meta_acc})}\n\n"

            async for chunk in ai_router.stream_chat(
                body.message,
                hist,
                body.language,
                body.model_preference,
                body.personality,
                bool(body.expert_mode),
                force_web_search=bool(body.web_search),
                document_id=body.document_id,
                create_mode=bool(body.create_mode),
                create_type=body.create_type,
                user_id=user_id,
                metadata_out=meta_acc,
            ):
                full.append(chunk)
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
            text = "".join(full)
            await _save_message(session_id, "user", body.message, None)
            await _save_message(session_id, "assistant", text, None)
            done_payload = {"done": True, "session_id": session_id, "metadata": meta_acc}
            yield f"data: {json.dumps(done_payload)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.get("/history/{session_id}")
async def get_history(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """Historique paginé des messages d'une session."""
    c = _client()
    if not c:
        return success_response(
            {"messages": [], "total": 0, "page": page, "page_size": page_size},
            "Sans base — historique vide",
        )
    try:
        conv = (
            c.table("chat_sessions")
            .select("id")
            .eq("id", session_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not conv.data:
            return error_response("Session introuvable", 404)
        res = (
            c.table("messages")
            .select("*")
            .eq("session_id", session_id)
            .order("created_at", desc=False)
            .execute()
        )
        rows = res.data or []
        total = len(rows)
        start = (page - 1) * page_size
        chunk = rows[start : start + page_size]
        return success_response(
            {
                "messages": chunk,
                "total": total,
                "page": page,
                "page_size": page_size,
            },
            "OK",
        )
    except Exception as e:
        return error_response(str(e), 500)


@router.get("/sessions")
async def list_sessions(user_id: str = Depends(get_current_user_id)):
    """Liste des conversations de l'utilisateur."""
    c = _client()
    if not c:
        return success_response([], "Sans base")
    try:
        res = (
            c.table("chat_sessions")
            .select("id,title,created_at,model_used")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return success_response(res.data or [], "OK")
    except Exception as e:
        return error_response(str(e), 500)


@router.delete("/session/{session_id}")
async def delete_session(session_id: str, user_id: str = Depends(get_current_user_id)):
    """Supprime une session et ses messages."""
    c = _client()
    if not c:
        return success_response(None, "Rien à supprimer")
    try:
        c.table("messages").delete().eq("session_id", session_id).execute()
        c.table("chat_sessions").delete().eq("id", session_id).eq("user_id", user_id).execute()
        return success_response({"deleted": session_id}, "Session supprimée")
    except Exception as e:
        return error_response(str(e), 500)
