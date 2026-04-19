"""
Tests de connectivité des intégrations externes SAYIBI AI (sans lancer le serveur HTTP).

Usage :
  pip install -r requirements.txt -r requirements-test.txt
  python test_apis.py

Variables lues depuis `.env` à la racine `sayibi_backend/`, puis `sql/.env` si présent
(le fichier racine surcharge `sql/.env`). Les tests sans clé sont marqués SKIP.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Awaitable, Callable, Tuple

import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

_ROOT = Path(__file__).resolve().parent
# sql/.env d'abord (ancien emplacement), puis .env racine qui prévaut
load_dotenv(_ROOT / "sql" / ".env")
load_dotenv(_ROOT / ".env", override=True)
console = Console(legacy_windows=False, emoji=False)


def _safe_cell(text: str, max_len: int = 120) -> str:
    """Réduit les emojis (réponses LLM) pour éviter les crash Rich sur cp1252 ; conserve le français."""
    s = (text or "")[:max_len]
    s = re.sub(r"[\U00010000-\U0010ffff]", "?", s)
    return s

TestFn = Callable[[], Awaitable[Tuple[str, str, str]]]
# returns: status "ok" | "skip" | "fail", label, message


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _skip(title: str, reason: str) -> Tuple[str, str, str]:
    return "skip", title, reason


async def test_groq() -> Tuple[str, str, str]:
    key = _env("GROQ_API_KEY")
    if not key:
        return _skip("Groq (Llama 3.3)", "GROQ_API_KEY manquant")
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": "Dis bonjour en français, une phrase."}],
        "max_tokens": 64,
    }
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(url, json=payload, headers=headers, timeout=45.0)
            r.raise_for_status()
            data = r.json()
            text = data["choices"][0]["message"]["content"][:120]
            return "ok", "Groq (Llama 3.3)", text.replace("\n", " ")
    except Exception as e:
        return "fail", "Groq (Llama 3.3)", str(e)[:200]


async def test_gemini() -> Tuple[str, str, str]:
    key = _env("GEMINI_API_KEY")
    if not key:
        return _skip("Google Gemini", "GEMINI_API_KEY manquant")
    try:
        from services import gemini_service

        resp, model = await gemini_service.generate_text(
            "Reply with one word: OK",
            [{"text": "Say OK"}],
            temperature=0.2,
        )
        text = gemini_service.parse_response_text(resp)
        preview = text.replace("\n", " ")[:120]
        return "ok", "Google Gemini", f"{model} — {preview}"
    except Exception as e:
        return "fail", "Google Gemini", str(e)[:200]


async def test_mistral() -> Tuple[str, str, str]:
    key = _env("MISTRAL_API_KEY")
    if not key:
        return _skip("Mistral AI", "MISTRAL_API_KEY manquant")
    url = "https://api.mistral.ai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {
        "model": "mistral-small-latest",
        "messages": [{"role": "user", "content": "Bonjour en une phrase."}],
        "max_tokens": 64,
    }
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(url, json=payload, headers=headers, timeout=45.0)
            r.raise_for_status()
            data = r.json()
            text = data["choices"][0]["message"]["content"][:120]
            return "ok", "Mistral AI", text.replace("\n", " ")
    except Exception as e:
        return "fail", "Mistral AI", str(e)[:200]


async def test_tavily() -> Tuple[str, str, str]:
    key = _env("TAVILY_API_KEY")
    if not key:
        return _skip("Tavily Search", "TAVILY_API_KEY manquant")
    url = "https://api.tavily.com/search"
    payload = {"api_key": key, "query": "Paris weather", "max_results": 2}
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(url, json=payload, timeout=45.0)
            r.raise_for_status()
            data = r.json()
            n = len(data.get("results") or [])
            return "ok", "Tavily Search", f"{n} résultat(s)"
    except Exception as e:
        return "fail", "Tavily Search", str(e)[:200]


async def test_elevenlabs() -> Tuple[str, str, str]:
    key = _env("ELEVENLABS_API_KEY")
    if not key:
        return _skip("ElevenLabs TTS", "ELEVENLABS_API_KEY manquant")
    url = "https://api.elevenlabs.io/v1/voices"
    headers = {"xi-api-key": key}
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, headers=headers, timeout=45.0)
            r.raise_for_status()
            data = r.json()
            n = len(data.get("voices") or [])
            return "ok", "ElevenLabs TTS", f"{n} voix"
    except Exception as e:
        return "fail", "ElevenLabs TTS", str(e)[:200]


async def test_upstash() -> Tuple[str, str, str]:
    base = _env("UPSTASH_REDIS_URL")
    token = _env("UPSTASH_REDIS_TOKEN")
    if not base or not token:
        return _skip("Upstash Redis", "UPSTASH_REDIS_URL ou UPSTASH_REDIS_TOKEN manquant")
    # API REST Upstash : GET {https_endpoint}/ping
    root = base.rstrip("/")
    if root.startswith("redis://") or root.startswith("rediss://"):
        return _skip(
            "Upstash Redis",
            "URL redis:// — utilisez l'endpoint HTTPS Upstash (REST) pour /ping",
        )
    url = f"{root}/ping"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, headers=headers, timeout=20.0)
            r.raise_for_status()
            body = r.text[:80]
            return "ok", "Upstash Redis", f"PING OK ({body})"
    except Exception as e:
        return "fail", "Upstash Redis", str(e)[:200]


async def test_pinecone() -> Tuple[str, str, str]:
    key = _env("PINECONE_API_KEY")
    name = _env("PINECONE_INDEX_NAME") or _env("PINECONE_INDEX") or "sayibi-memory"
    if not key:
        return _skip("Pinecone", "PINECONE_API_KEY manquant")
    try:
        from pinecone import Pinecone

        pc = Pinecone(api_key=key)
        pc.describe_index(name)
        return "ok", "Pinecone", f"Index « {name} » accessible"
    except Exception as e:
        return "fail", "Pinecone", str(e)[:200]


async def test_cloudflare_r2() -> Tuple[str, str, str]:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError

    from core.config import get_settings

    s = get_settings()
    if not all([s.r2_account_id, s.r2_access_key, s.r2_secret_key, s.r2_bucket]):
        return _skip("Cloudflare R2", "Variables R2 incomplètes")
    ak = (s.r2_access_key or "").strip()
    if len(ak) != 32:
        return (
            "fail",
            "Cloudflare R2",
            "R2_ACCESS_KEY_ID = Access Key ID du jeton R2 (Manage R2 API Tokens), "
            f"exactement 32 caractères hex. Actuellement : {len(ak)} car. "
            "Ne pas utiliser un API Token Cloudflare général (souvent 40+ car.).",
        )
    endpoint = s.r2_endpoint
    if not endpoint:
        return "fail", "Cloudflare R2", "R2_ACCOUNT_ID ou R2_S3_ENDPOINT invalide"
    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=s.r2_access_key,
            aws_secret_access_key=s.r2_secret_key,
            region_name="auto",
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
            ),
        )
        s3.head_bucket(Bucket=s.r2_bucket)
        hint = ""
        if (s.r2_jurisdiction or "").lower() in ("eu", "europe"):
            hint = " (endpoint EU)"
        return "ok", "Cloudflare R2", f"Bucket « {s.r2_bucket} » OK{hint}"
    except ClientError as e:
        return "fail", "Cloudflare R2", str(e)[:200]
    except Exception as e:
        return "fail", "Cloudflare R2", str(e)[:200]


async def test_supabase() -> Tuple[str, str, str]:
    url = _env("SUPABASE_URL")
    key = _env("SUPABASE_SERVICE_KEY") or _env("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return _skip("Supabase DB", "SUPABASE_URL ou SUPABASE_SERVICE_KEY manquant")
    try:
        from supabase import create_client

        client = create_client(url, key)
        res = client.table("developer_context").select("key").limit(1).execute()
        n = len(res.data or [])
        return "ok", "Supabase DB", f"{n} ligne(s) lue(s) (developer_context)"
    except Exception as e:
        return "fail", "Supabase DB", str(e)[:200]


async def test_firebase_fcm() -> Tuple[str, str, str]:
    raw = _env("FIREBASE_CREDENTIALS_JSON")
    path = _env("FIREBASE_CREDENTIALS_PATH")
    if not raw and not (path and os.path.isfile(os.path.expanduser(path))):
        return _skip(
            "Firebase FCM v1",
            "FIREBASE_CREDENTIALS_JSON ou fichier FIREBASE_CREDENTIALS_PATH manquant",
        )
    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account

        scope = "https://www.googleapis.com/auth/firebase.messaging"
        if raw:
            info = json.loads(raw)
            creds = service_account.Credentials.from_service_account_info(info, scopes=[scope])
        else:
            creds = service_account.Credentials.from_service_account_file(
                os.path.expanduser(path),
                scopes=[scope],
            )
        creds.refresh(Request())
        tok = creds.token or ""
        preview = f"{tok[:12]}…" if len(tok) > 12 else "(vide)"
        return "ok", "Firebase FCM v1", f"Jeton OAuth2 {preview}"
    except Exception as e:
        return "fail", "Firebase FCM v1", str(e)[:200]


async def test_backend_health() -> Tuple[str, str, str]:
    base = _env("SAYIBI_DEPLOY_URL").rstrip("/")
    if not base:
        return _skip(
            "Backend /health",
            "SAYIBI_DEPLOY_URL non défini (ex: https://sayibi-backend.onrender.com)",
        )
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{base}/health", timeout=20.0)
            r.raise_for_status()
            return "ok", "Backend /health", r.text[:120]
    except Exception as e:
        return "fail", "Backend /health", str(e)[:200]


TESTS: list[tuple[str, TestFn]] = [
    ("Groq", test_groq),
    ("Gemini", test_gemini),
    ("Mistral", test_mistral),
    ("Tavily", test_tavily),
    ("ElevenLabs", test_elevenlabs),
    ("Upstash", test_upstash),
    ("Pinecone", test_pinecone),
    ("R2", test_cloudflare_r2),
    ("Supabase", test_supabase),
    ("FCM v1", test_firebase_fcm),
    ("HTTP /health", test_backend_health),
]


async def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    console.print("\n[bold cyan]SAYIBI AI — Tests d'intégration (clés externes)[/bold cyan]\n")

    table = Table(title="Résultats")
    table.add_column("Service", style="cyan", width=24)
    table.add_column("Statut", width=10)
    table.add_column("Détail", style="dim", width=60)

    fails = 0
    for _slug, fn in TESTS:
        status, label, msg = await fn()
        if status == "ok":
            st = "[green]OK[/green]"
        elif status == "skip":
            st = "[yellow]SKIP[/yellow]"
        else:
            st = "[red]FAIL[/red]"
            fails += 1
        table.add_row(label, st, _safe_cell(msg))

    console.print(table)
    console.print(
        "\n[dim]Astuce : SAYIBI_DEPLOY_URL=https://votre-service.onrender.com pour tester GET /health[/dim]\n",
    )

    if fails:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
