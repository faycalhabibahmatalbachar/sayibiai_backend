"""Recherche web et réponse synthétisée."""

from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from core.deps import get_current_user_id
from core.responses import error_response, success_response
from services import ai_router, search_service
from services.usage_service import log_usage

router = APIRouter(prefix="/search", tags=["search"])


class WebSearchBody(BaseModel):
    query: str
    language: str = "fr"
    max_results: int = Field(5, ge=1, le=10)


class SemanticSearchBody(BaseModel):
    question: str


class AnswerBody(BaseModel):
    question: str


@router.post("/web")
async def web_search_ep(body: WebSearchBody, user_id: str = Depends(get_current_user_id)):
    """Recherche web (Tavily puis DuckDuckGo)."""
    try:
        results = await search_service.web_search(body.query, body.max_results)
    except Exception as e:
        return error_response(str(e), 502)
    await log_usage(user_id, "/search/web", None, "search")
    return success_response({"results": results}, "OK")


@router.post("/semantic")
async def semantic_search(body: SemanticSearchBody, user_id: str = Depends(get_current_user_id)):
    """Recherche dans la mémoire utilisateur — alias vers réponse web + contexte (MVP)."""
    try:
        results = await search_service.web_search(body.question, 5)
    except Exception as e:
        return error_response(str(e), 502)
    await log_usage(user_id, "/search/semantic", None, "search")
    return success_response({"results": results}, "OK")


@router.post("/answer")
async def search_answer(body: AnswerBody, user_id: str = Depends(get_current_user_id)):
    """Recherche web + synthèse LLM avec sources."""
    try:
        results = await search_service.web_search(body.question, 5)
    except Exception as e:
        return error_response(str(e), 502)
    ctx_lines: List[str] = []
    sources: List[str] = []
    for r in results:
        ctx_lines.append(f"- {r.get('title')}: {r.get('snippet')}")
        if r.get("url"):
            sources.append(r["url"])
    prompt = (
        f"Question : {body.question}\n\nContexte :\n"
        + "\n".join(ctx_lines)
        + "\n\nRéponds de façon concise en citant implicitement les sources."
    )
    try:
        answer, model, tok = await ai_router.run_chat(
            prompt,
            [],
            "fr",
            "auto",
            None,
            False,
            need_vision=False,
        )
    except Exception as e:
        return error_response(str(e), 500)
    await log_usage(user_id, "/search/answer", tok, model)
    return success_response({"answer": answer, "sources": sources}, "OK")
