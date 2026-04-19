"""Recherche web : Serper → Tavily → DuckDuckGo (ddgs)."""

from typing import Any, Dict, List

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


async def serper_search(
    query: str,
    max_results: int = 5,
) -> List[Dict[str, Any]]:
    """Recherche Google via Serper.dev (JSON)."""
    settings = get_settings()
    key = (settings.serper_api_key or "").strip()
    if not key:
        return []
    url = "https://google.serper.dev/search"
    payload = {"q": query, "num": min(max_results, 10)}
    headers = {"X-API-KEY": key, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=45.0) as client:
        r = await client.post(url, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    out: List[Dict[str, Any]] = []
    for item in (data.get("organic") or [])[:max_results]:
        out.append(
            {
                "title": item.get("title") or "",
                "url": item.get("link") or "",
                "snippet": item.get("snippet") or "",
                "score": 1.0,
            },
        )
    return out


def _duckduckgo_images_sync(query: str, max_results: int = 8) -> List[Dict[str, Any]]:
    """Images DuckDuckGo (fallback sans clé Serper)."""
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS  # type: ignore
    out: List[Dict[str, Any]] = []
    try:
        with DDGS() as ddgs:
            for i, r in enumerate(ddgs.images(query, max_results=max_results)):
                img = (r.get("image") or r.get("thumbnail") or "").strip()
                if not img:
                    continue
                out.append(
                    {
                        "url": img,
                        "title": (r.get("title") or "")[:200],
                        "source_url": (r.get("url") or "")[:500],
                    },
                )
                if len(out) >= max_results:
                    break
    except Exception:
        return []
    return out


async def web_image_search(
    query: str,
    max_results: int = 8,
) -> List[Dict[str, Any]]:
    """Aperçus images pour enrichir la conversation (Serper Images si clé, sinon DDG)."""
    settings = get_settings()
    key = (settings.serper_api_key or "").strip()
    if key:
        try:
            url = "https://google.serper.dev/images"
            payload = {"q": query, "num": min(max_results, 10)}
            headers = {"X-API-KEY": key, "Content-Type": "application/json"}
            async with httpx.AsyncClient(timeout=35.0) as client:
                r = await client.post(url, json=payload, headers=headers)
                r.raise_for_status()
                data = r.json()
            out: List[Dict[str, Any]] = []
            for item in (data.get("images") or [])[:max_results]:
                img_url = (item.get("imageUrl") or item.get("thumbnailUrl") or "").strip()
                if not img_url:
                    continue
                out.append(
                    {
                        "url": img_url,
                        "title": (item.get("title") or "")[:200],
                        "source_url": (item.get("link") or "")[:500],
                    },
                )
            if out:
                return out
        except Exception:
            pass
    import asyncio

    return await asyncio.to_thread(_duckduckgo_images_sync, query, max_results)


async def web_search(
    query: str,
    max_results: int = 5,
) -> List[Dict[str, Any]]:
    """Serper (si clé) → Tavily → repli DDG."""
    s = get_settings()
    if (s.serper_api_key or "").strip():
        try:
            serp = await serper_search(query, max_results)
            if serp:
                return serp
        except Exception:
            pass
    t = await tavily_search(query, max_results)
    if t:
        return t
    import asyncio

    return await asyncio.to_thread(duckduckgo_search_sync, query, max_results)
