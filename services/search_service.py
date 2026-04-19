"""Recherche web : Tavily en priorité, repli DuckDuckGo (ddgs)."""

from typing import Any, Dict, List, Optional

import httpx

from core.config import get_settings


async def tavily_search(
    query: str,
    max_results: int = 5,
) -> List[Dict[str, Any]]:
    """Recherche via API Tavily."""
    settings = get_settings()
    if not settings.tavily_api_key:
        return []
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": settings.tavily_api_key,
        "query": query,
        "max_results": max_results,
        "include_answer": False,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        data = r.json()
    results: List[Dict[str, Any]] = []
    for item in data.get("results") or []:
        results.append(
            {
                "title": item.get("title") or "",
                "url": item.get("url") or "",
                "snippet": item.get("content") or item.get("snippet") or "",
                "score": item.get("score"),
            }
        )
    return results


def duckduckgo_search_sync(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """Recherche DuckDuckGo (bloquant — à appeler via asyncio.to_thread)."""
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS  # type: ignore
    results: List[Dict[str, Any]] = []
    with DDGS() as ddgs:
        for i, r in enumerate(ddgs.text(query, max_results=max_results)):
            results.append(
                {
                    "title": r.get("title") or "",
                    "url": r.get("href") or r.get("url") or "",
                    "snippet": r.get("body") or "",
                    "score": 1.0 - (i * 0.05),
                }
            )
    return results


async def web_search(
    query: str,
    max_results: int = 5,
) -> List[Dict[str, Any]]:
    """Tavily puis repli DDG."""
    t = await tavily_search(query, max_results)
    if t:
        return t
    import asyncio

    return await asyncio.to_thread(duckduckgo_search_sync, query, max_results)
