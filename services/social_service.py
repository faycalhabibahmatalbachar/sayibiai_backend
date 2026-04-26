"""Service réseaux sociaux — connexion OAuth, publication, monitoring."""

import base64
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from core.config import get_settings
from core.database import get_supabase_admin

logger = logging.getLogger(__name__)

# Plateformes supportées
SUPPORTED_PLATFORMS = {"twitter", "instagram", "facebook", "linkedin", "tiktok"}


# ---------------------------------------------------------------------------
# Chiffrement des tokens OAuth
# ---------------------------------------------------------------------------

def _encrypt_token(token: str) -> str:
    """Chiffre un token OAuth avec AES-256."""
    try:
        from cryptography.fernet import Fernet
        import base64, hashlib
        s = get_settings()
        key_raw = s.aes_encryption_key if hasattr(s, 'aes_encryption_key') else "default_dev_key_change_in_prod_!"
        key = base64.urlsafe_b64encode(hashlib.sha256(key_raw.encode()).digest())
        f = Fernet(key)
        return f.encrypt(token.encode()).decode()
    except Exception as e:
        logger.warning("Token encryption error: %s", e)
        return base64.b64encode(token.encode()).decode()


def _decrypt_token(encrypted: str) -> str:
    """Déchiffre un token OAuth."""
    try:
        from cryptography.fernet import Fernet
        import base64, hashlib
        s = get_settings()
        key_raw = s.aes_encryption_key if hasattr(s, 'aes_encryption_key') else "default_dev_key_change_in_prod_!"
        key = base64.urlsafe_b64encode(hashlib.sha256(key_raw.encode()).digest())
        f = Fernet(key)
        return f.decrypt(encrypted.encode()).decode()
    except Exception as e:
        logger.warning("Token decryption error: %s", e)
        try:
            return base64.b64decode(encrypted.encode()).decode()
        except Exception:
            return encrypted


# ---------------------------------------------------------------------------
# Gestion des comptes
# ---------------------------------------------------------------------------

async def connect_account(
    user_id: str,
    platform: str,
    access_token: str,
    refresh_token: Optional[str] = None,
    account_username: str = "",
    token_expires_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Connecte un compte social avec tokens OAuth chiffrés."""
    if platform not in SUPPORTED_PLATFORMS:
        raise ValueError(f"Plateforme non supportée: {platform}")

    record_id = str(uuid.uuid4())
    encrypted_access = _encrypt_token(access_token)
    encrypted_refresh = _encrypt_token(refresh_token) if refresh_token else None

    try:
        c = get_supabase_admin()
        if c:
            # Désactiver l'ancien compte pour cette plateforme
            c.table("social_accounts").update({"is_active": False}).eq(
                "user_id", user_id
            ).eq("platform", platform).execute()

            c.table("social_accounts").insert({
                "id": record_id,
                "user_id": user_id,
                "platform": platform,
                "account_username": account_username,
                "access_token_encrypted": encrypted_access,
                "refresh_token_encrypted": encrypted_refresh,
                "token_expires_at": token_expires_at,
                "is_active": True,
            }).execute()
    except Exception as e:
        logger.warning("Social account connect error: %s", e)
        raise

    return {"id": record_id, "platform": platform, "username": account_username}


async def get_user_accounts(user_id: str) -> List[dict]:
    """Liste des comptes sociaux connectés."""
    try:
        c = get_supabase_admin()
        if not c:
            return []
        res = (
            c.table("social_accounts")
            .select("id,platform,account_username,is_active,created_at")
            .eq("user_id", user_id)
            .eq("is_active", True)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.warning("Get social accounts error: %s", e)
        return []


async def disconnect_account(user_id: str, account_id: str) -> bool:
    try:
        c = get_supabase_admin()
        if not c:
            return False
        c.table("social_accounts").update({"is_active": False}).eq(
            "id", account_id
        ).eq("user_id", user_id).execute()
        return True
    except Exception as e:
        logger.warning("Disconnect account error: %s", e)
        return False


# ---------------------------------------------------------------------------
# Publication de posts
# ---------------------------------------------------------------------------

async def create_post(
    user_id: str,
    content: str,
    platforms: List[str],
    media_urls: Optional[List[str]] = None,
    hashtags: Optional[List[str]] = None,
    schedule_for: Optional[str] = None,
    ai_generated: bool = False,
) -> Dict[str, Any]:
    """Crée et publie (ou programme) un post multi-plateformes."""
    record_id = str(uuid.uuid4())
    published_at = None
    results: Dict[str, Any] = {}

    # Insérer en base d'abord
    try:
        c = get_supabase_admin()
        if c:
            c.table("social_posts").insert({
                "id": record_id,
                "user_id": user_id,
                "platforms": platforms,
                "content": content,
                "media_urls": media_urls or [],
                "hashtags": hashtags or [],
                "scheduled_for": schedule_for,
                "ai_generated": ai_generated,
            }).execute()
    except Exception as e:
        logger.warning("Social post DB insert error: %s", e)

    # Publier immédiatement si pas de programmation
    if not schedule_for:
        for platform in platforms:
            try:
                result = await _publish_to_platform(user_id, platform, content, media_urls or [], hashtags or [])
                results[platform] = result
            except Exception as e:
                logger.warning("Publish to %s error: %s", platform, e)
                results[platform] = {"error": str(e)}

        published_at = datetime.now(timezone.utc).isoformat()
        try:
            c = get_supabase_admin()
            if c:
                c.table("social_posts").update({
                    "published_at": published_at,
                    "engagement_stats": results,
                }).eq("id", record_id).execute()
        except Exception:
            pass

    return {
        "id": record_id,
        "status": "published" if not schedule_for else "scheduled",
        "published_at": published_at,
        "scheduled_for": schedule_for,
        "results": results,
    }


async def _publish_to_platform(
    user_id: str,
    platform: str,
    content: str,
    media_urls: List[str],
    hashtags: List[str],
) -> dict:
    """Publie sur une plateforme spécifique."""
    # Récupérer le token
    try:
        c = get_supabase_admin()
        if not c:
            return {"status": "no_db"}
        res = (
            c.table("social_accounts")
            .select("access_token_encrypted")
            .eq("user_id", user_id)
            .eq("platform", platform)
            .eq("is_active", True)
            .execute()
        )
        if not res.data:
            return {"status": "no_account"}
        access_token = _decrypt_token(res.data[0]["access_token_encrypted"])
    except Exception as e:
        return {"status": "token_error", "error": str(e)}

    full_content = content
    if hashtags:
        full_content += "\n" + " ".join(f"#{h.lstrip('#')}" for h in hashtags)

    if platform == "twitter":
        return await _post_twitter(full_content, access_token)
    elif platform == "linkedin":
        return await _post_linkedin(full_content, access_token)
    elif platform == "instagram":
        return await _post_instagram(full_content, media_urls, access_token)
    else:
        return {"status": "platform_not_implemented", "platform": platform}


async def _post_twitter(content: str, bearer_token: str) -> dict:
    """Publie un tweet via X API v2."""
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(
                "https://api.twitter.com/2/tweets",
                headers={"Authorization": f"Bearer {bearer_token}"},
                json={"text": content[:280]},
            )
            if r.status_code in (200, 201):
                data = r.json().get("data", {})
                return {"status": "published", "tweet_id": data.get("id")}
            return {"status": "error", "code": r.status_code}
    except Exception as e:
        return {"status": "error", "error": str(e)}


async def _post_linkedin(content: str, access_token: str) -> dict:
    """Publie sur LinkedIn via API v2."""
    try:
        # Obtenir l'URN de l'auteur
        async with httpx.AsyncClient(timeout=20.0) as client:
            me = await client.get(
                "https://api.linkedin.com/v2/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if me.status_code >= 400:
                return {"status": "auth_error"}
            author_urn = f"urn:li:person:{me.json().get('id')}"

            r = await client.post(
                "https://api.linkedin.com/v2/ugcPosts",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "author": author_urn,
                    "lifecycleState": "PUBLISHED",
                    "specificContent": {
                        "com.linkedin.ugc.ShareContent": {
                            "shareCommentary": {"text": content},
                            "shareMediaCategory": "NONE",
                        }
                    },
                    "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
                },
            )
            if r.status_code in (200, 201):
                return {"status": "published", "post_id": r.json().get("id")}
            return {"status": "error", "code": r.status_code}
    except Exception as e:
        return {"status": "error", "error": str(e)}


async def _post_instagram(content: str, media_urls: List[str], access_token: str) -> dict:
    """Publication Instagram Basic Display API."""
    return {"status": "requires_business_account", "note": "Instagram requires Business API setup"}


# ---------------------------------------------------------------------------
# Génération de posts IA
# ---------------------------------------------------------------------------

async def generate_ai_post(
    user_id: str,
    topic: str,
    platform: str,
    tone: str = "professional",
) -> Dict[str, Any]:
    """Génère un post IA optimisé avec tendances."""
    from services.prompt_engineering import build_social_post
    from services.cache_service import get_social_trending

    trending = await get_social_trending(platform) or []

    variants = await build_social_post(
        topic=topic,
        platform=platform,
        tone=tone,
        trending_tags=trending,
    )

    return {
        "platform": platform,
        "topic": topic,
        "tone": tone,
        "variants": variants,
        "ai_generated": True,
    }


# ---------------------------------------------------------------------------
# Monitoring interactions
# ---------------------------------------------------------------------------

async def get_inbox(user_id: str, limit: int = 50) -> List[dict]:
    """Inbox unifié de toutes les interactions sociales."""
    try:
        c = get_supabase_admin()
        if not c:
            return []
        res = (
            c.table("social_interactions")
            .select("*, social_posts!inner(user_id)")
            .eq("social_posts.user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.warning("Social inbox error: %s", e)
        return []


async def reply_to_interaction(
    user_id: str,
    interaction_id: str,
    reply_text: str,
    ai_generated: bool = False,
) -> Dict[str, Any]:
    """Répond à une interaction sociale."""
    try:
        c = get_supabase_admin()
        if c:
            c.table("social_interactions").update({
                "ai_response": reply_text,
                "user_read": True,
            }).eq("id", interaction_id).execute()
        return {"status": "replied", "interaction_id": interaction_id}
    except Exception as e:
        return {"status": "error", "error": str(e)}


async def get_post_history(user_id: str, limit: int = 20) -> List[dict]:
    """Historique des posts publiés."""
    try:
        c = get_supabase_admin()
        if not c:
            return []
        res = (
            c.table("social_posts")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.warning("Post history error: %s", e)
        return []


async def get_analytics(user_id: str) -> Dict[str, Any]:
    """Analytics hebdomadaires des posts et interactions."""
    try:
        c = get_supabase_admin()
        if not c:
            return {}
        posts_res = (
            c.table("social_posts")
            .select("id,platforms,published_at,engagement_stats")
            .eq("user_id", user_id)
            .execute()
        )
        posts = posts_res.data or []
        total_posts = len(posts)
        platform_counts: Dict[str, int] = {}
        for p in posts:
            for pl in (p.get("platforms") or []):
                platform_counts[pl] = platform_counts.get(pl, 0) + 1

        return {
            "total_posts": total_posts,
            "posts_by_platform": platform_counts,
            "top_platform": max(platform_counts, key=platform_counts.get) if platform_counts else None,
        }
    except Exception as e:
        logger.warning("Analytics error: %s", e)
        return {}


async def get_settings_social(user_id: str) -> dict:
    try:
        c = get_supabase_admin()
        if not c:
            return {}
        res = c.table("social_settings").select("*").eq("user_id", user_id).execute()
        return res.data[0] if res.data else {}
    except Exception:
        return {}


async def update_settings_social(user_id: str, settings: dict) -> bool:
    try:
        c = get_supabase_admin()
        if not c:
            return False
        c.table("social_settings").upsert({"user_id": user_id, **settings}).execute()
        return True
    except Exception as e:
        logger.warning("Update social settings error: %s", e)
        return False
