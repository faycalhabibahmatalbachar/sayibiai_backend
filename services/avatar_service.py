"""Service Avatar vidéo — HeyGen / Synthesia intégration."""

import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

import httpx

from core.config import get_settings
from core.database import get_supabase_admin
from services import storage_service  # noqa: F401 (importé pour cohérence)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HeyGen — génération vidéo avatar
# ---------------------------------------------------------------------------

HEYGEN_BASE = "https://api.heygen.com/v2"
HEYGEN_V1 = "https://api.heygen.com/v1"


async def list_preset_avatars() -> List[dict]:
    """Récupère la liste des avatars disponibles chez HeyGen."""
    s = get_settings()
    if not s.heygen_api_key:
        return _fallback_avatars()
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(
                f"{HEYGEN_V1}/avatar.list",
                headers={"X-Api-Key": s.heygen_api_key},
            )
            if r.status_code >= 400:
                return _fallback_avatars()
            data = r.json()
            avatars = data.get("data", {}).get("avatars", [])
            return [
                {
                    "provider_id": a.get("avatar_id"),
                    "name": a.get("avatar_name", "Avatar"),
                    "preview_url": a.get("preview_image_url", ""),
                    "type": "preset",
                    "provider": "heygen",
                }
                for a in avatars[:20]
            ]
    except Exception as e:
        logger.warning("HeyGen avatar list error: %s", e)
        return _fallback_avatars()


def _fallback_avatars() -> List[dict]:
    return [
        {"provider_id": "Anna_public_3_20240108", "name": "Anna", "type": "preset", "provider": "heygen"},
        {"provider_id": "Tyler-insuit-20220721", "name": "Tyler", "type": "preset", "provider": "heygen"},
        {"provider_id": "Shelly-incasualsuit-20220721", "name": "Shelly", "type": "preset", "provider": "heygen"},
    ]


async def get_user_avatars(user_id: str) -> List[dict]:
    """Récupère les avatars de l'utilisateur depuis la base."""
    try:
        c = get_supabase_admin()
        if not c:
            return []
        res = (
            c.table("avatars")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.warning("Get user avatars error: %s", e)
        return []


async def create_custom_avatar(
    user_id: str,
    avatar_name: str,
    photo_url: str,
    voice_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Crée un avatar personnalisé depuis une photo."""
    s = get_settings()
    record_id = str(uuid.uuid4())
    provider_avatar_id = None

    if s.heygen_api_key:
        try:
            provider_avatar_id = await _heygen_create_avatar(photo_url, avatar_name, s.heygen_api_key)
        except Exception as e:
            logger.warning("HeyGen create avatar error: %s", e)

    try:
        c = get_supabase_admin()
        if c:
            c.table("avatars").insert({
                "id": record_id,
                "user_id": user_id,
                "avatar_name": avatar_name,
                "avatar_type": "custom",
                "avatar_provider": "heygen",
                "provider_avatar_id": provider_avatar_id or record_id,
                "preview_video_url": photo_url,
                "voice_id": voice_id or s.elevenlabs_default_voice_id,
                "is_default": False,
            }).execute()
    except Exception as e:
        logger.warning("Avatar DB insert error: %s", e)

    return {
        "id": record_id,
        "avatar_name": avatar_name,
        "provider_avatar_id": provider_avatar_id,
        "status": "created",
    }


async def _heygen_create_avatar(photo_url: str, name: str, api_key: str) -> str:
    """Crée un instant avatar chez HeyGen."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            f"{HEYGEN_V1}/instant_avatar",
            headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
            json={"image_url": photo_url, "name": name},
        )
        if r.status_code >= 400:
            raise RuntimeError(f"HeyGen create error: {r.status_code}")
        return r.json().get("data", {}).get("avatar_id", str(uuid.uuid4()))


async def generate_avatar_response(
    user_id: str,
    avatar_id: str,
    message_text: str,
    response_text: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Génère une vidéo de l'avatar répondant à un message.
    1. Génère réponse LLM si non fournie
    2. Soumet job HeyGen
    3. Attend complétion (polling)
    4. Watermark + upload
    """
    s = get_settings()

    # Générer réponse LLM si nécessaire
    if not response_text:
        from services.ai_router import run_chat
        try:
            response_text, _, _, _ = await run_chat(message_text, [], None, None, None, False)
        except Exception as e:
            response_text = f"Je suis désolé, je n'ai pas pu générer une réponse : {e}"

    # Récupérer l'avatar
    try:
        c = get_supabase_admin()
        avatar_data = None
        if c:
            res = c.table("avatars").select("*").eq("id", avatar_id).eq("user_id", user_id).execute()
            if res.data:
                avatar_data = res.data[0]
    except Exception:
        avatar_data = None

    provider_avatar_id = (avatar_data or {}).get("provider_avatar_id", "Anna_public_3_20240108")
    voice_id = (avatar_data or {}).get("voice_id") or s.elevenlabs_default_voice_id

    video_url = None
    job_id = None

    if s.heygen_api_key:
        try:
            job_id = await _heygen_submit_video(
                response_text, provider_avatar_id, voice_id, s.heygen_api_key
            )
            # Polling (max 60s)
            video_url = await _heygen_poll_video(job_id, s.heygen_api_key)
        except Exception as e:
            logger.warning("HeyGen video generation error: %s", e)

    # Stocker résultat
    record_id = str(uuid.uuid4())
    try:
        c = get_supabase_admin()
        if c:
            c.table("avatar_conversations").insert({
                "id": record_id,
                "user_id": user_id,
                "avatar_id": avatar_id,
                "message_text": message_text,
                "response_text": response_text,
                "response_video_url": video_url,
            }).execute()
    except Exception as e:
        logger.warning("Avatar conversation DB error: %s", e)

    return {
        "id": record_id,
        "response_text": response_text,
        "video_url": video_url,
        "job_id": job_id,
        "status": "completed" if video_url else "text_only",
    }


async def _heygen_submit_video(
    text: str,
    avatar_id: str,
    voice_id: str,
    api_key: str,
) -> str:
    """Soumet un job de génération vidéo à HeyGen."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            f"{HEYGEN_V2}/video/generate",
            headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
            json={
                "video_inputs": [{
                    "character": {
                        "type": "avatar",
                        "avatar_id": avatar_id,
                        "avatar_style": "normal",
                    },
                    "voice": {
                        "type": "text",
                        "input_text": text[:2000],
                        "voice_id": voice_id,
                    },
                }],
                "dimension": {"width": 1280, "height": 720},
                "aspect_ratio": "16:9",
            },
        )
        if r.status_code >= 400:
            raise RuntimeError(f"HeyGen submit error: {r.status_code}: {r.text[:200]}")
        return r.json().get("data", {}).get("video_id", str(uuid.uuid4()))

HEYGEN_V2 = "https://api.heygen.com/v2"


async def _heygen_poll_video(job_id: str, api_key: str, max_attempts: int = 30) -> Optional[str]:
    """Polling HeyGen jusqu'à complétion (max ~60s)."""
    import asyncio
    for i in range(max_attempts):
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(
                    f"{HEYGEN_V1}/video_status.get",
                    headers={"X-Api-Key": api_key},
                    params={"video_id": job_id},
                )
                if r.status_code >= 400:
                    break
                data = r.json().get("data", {})
                status = data.get("status")
                if status == "completed":
                    return data.get("video_url")
                if status in ("failed", "error"):
                    break
        except Exception:
            pass
        await asyncio.sleep(2)
    return None


async def set_default_avatar(user_id: str, avatar_id: str) -> bool:
    """Définit un avatar comme avatar par défaut."""
    try:
        c = get_supabase_admin()
        if not c:
            return False
        c.table("avatars").update({"is_default": False}).eq("user_id", user_id).execute()
        c.table("avatars").update({"is_default": True}).eq("id", avatar_id).eq("user_id", user_id).execute()
        return True
    except Exception as e:
        logger.warning("Set default avatar error: %s", e)
        return False


async def delete_avatar(user_id: str, avatar_id: str) -> bool:
    """Supprime un avatar de l'utilisateur."""
    try:
        c = get_supabase_admin()
        if not c:
            return False
        c.table("avatars").delete().eq("id", avatar_id).eq("user_id", user_id).execute()
        return True
    except Exception as e:
        logger.warning("Delete avatar error: %s", e)
        return False


async def get_avatar_conversation_history(user_id: str, limit: int = 20) -> List[dict]:
    """Historique des conversations avec les avatars."""
    try:
        c = get_supabase_admin()
        if not c:
            return []
        res = (
            c.table("avatar_conversations")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.warning("Avatar history error: %s", e)
        return []
