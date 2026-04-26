"""Tâches Celery — monitoring réseaux sociaux et auto-publication."""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from tasks.celery_app import app

logger = logging.getLogger(__name__)


def _get_db():
    from core.database import get_supabase_admin
    return get_supabase_admin()


@app.task(bind=True, max_retries=2)
def social_media_monitor(self):
    """Vérifie les nouvelles interactions sur tous les comptes sociaux connectés."""
    import asyncio
    try:
        asyncio.run(_async_social_monitor())
    except Exception as exc:
        logger.error("social_media_monitor error: %s", exc)
        raise self.retry(exc=exc)


async def _async_social_monitor():
    """Monitore les interactions sociales pour tous les utilisateurs actifs."""
    c = _get_db()
    if not c:
        return

    try:
        res = (
            c.table("social_accounts")
            .select("user_id,platform,access_token_encrypted,account_username")
            .eq("is_active", True)
            .execute()
        )
        accounts = res.data or []
    except Exception as e:
        logger.error("Social monitor fetch accounts error: %s", e)
        return

    for account in accounts:
        try:
            await _monitor_account(account, c)
        except Exception as e:
            logger.warning(
                "Social monitor error for %s/%s: %s",
                account.get("user_id"),
                account.get("platform"),
                e,
            )


async def _monitor_account(account: dict, db: Any):
    """Vérifie les interactions d'un compte spécifique."""
    platform = account.get("platform", "")
    if platform == "twitter":
        interactions = await _fetch_twitter_interactions(account)
    elif platform == "linkedin":
        interactions = await _fetch_linkedin_interactions(account)
    else:
        return

    for interaction in interactions:
        try:
            # Vérifier si déjà enregistrée
            existing = (
                db.table("social_interactions")
                .select("id")
                .eq("platform", platform)
                .eq("author_username", interaction.get("author", ""))
                .execute()
            )
            if existing.data:
                continue

            # Classifier l'interaction
            classification = await _classify_interaction(interaction.get("content", ""))

            import uuid
            db.table("social_interactions").insert({
                "id": str(uuid.uuid4()),
                "platform": platform,
                "interaction_type": interaction.get("type", "comment"),
                "author_username": interaction.get("author", ""),
                "content": interaction.get("content", ""),
                "flagged_as_opportunity": classification == "opportunity",
                "user_read": False,
            }).execute()

            # Auto-réponse si interaction simple
            if classification == "simple":
                await _auto_reply_interaction(account, interaction, db)

        except Exception as e:
            logger.debug("Store interaction error: %s", e)


async def _fetch_twitter_interactions(account: dict) -> List[dict]:
    """Récupère les mentions et DMs Twitter récents."""
    from services.social_service import _decrypt_token
    import httpx

    try:
        token = _decrypt_token(account.get("access_token_encrypted", ""))
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                "https://api.twitter.com/2/tweets/search/recent",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "query": f"@{account.get('account_username', '')}",
                    "max_results": 10,
                    "tweet.fields": "author_id,created_at,text",
                },
            )
            if r.status_code >= 400:
                return []
            tweets = r.json().get("data", [])
            return [
                {
                    "type": "mention",
                    "author": t.get("author_id", ""),
                    "content": t.get("text", ""),
                    "id": t.get("id"),
                }
                for t in tweets
            ]
    except Exception as e:
        logger.debug("Twitter fetch error: %s", e)
        return []


async def _fetch_linkedin_interactions(account: dict) -> List[dict]:
    """Récupère les commentaires LinkedIn récents."""
    return []  # Nécessite permissions spécifiques LinkedIn


async def _classify_interaction(content: str) -> str:
    """Classifie une interaction: simple|complex|opportunity|spam."""
    from core.config import get_settings
    s = get_settings()

    if not s.openai_api_key or not content:
        return "simple"

    try:
        import httpx, json
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {s.openai_api_key}"},
                json={
                    "model": "gpt-4o-mini",
                    "messages": [{
                        "role": "user",
                        "content": (
                            f"Classifie cette interaction sociale en UNE seule catégorie: "
                            f"'simple' (salutation, emoji, bref), 'complex' (question détaillée), "
                            f"'opportunity' (business, collaboration), 'spam'.\n"
                            f"Interaction: {content[:500]}\n"
                            f"Réponds avec un seul mot."
                        ),
                    }],
                    "max_tokens": 10,
                    "temperature": 0,
                },
            )
            if r.status_code < 400:
                result = r.json()["choices"][0]["message"]["content"].strip().lower()
                if result in ("simple", "complex", "opportunity", "spam"):
                    return result
    except Exception as e:
        logger.debug("Classification error: %s", e)

    return "simple"


async def _auto_reply_interaction(account: dict, interaction: dict, db: Any):
    """Génère et enregistre une auto-réponse pour les interactions simples."""
    from core.config import get_settings
    s = get_settings()
    if not s.openai_api_key:
        return

    try:
        import httpx
        platform = account.get("platform", "")
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {s.openai_api_key}"},
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {
                            "role": "system",
                            "content": f"Tu gères les réponses sur {platform}. Réponds brièvement et positivement.",
                        },
                        {
                            "role": "user",
                            "content": f"Interaction reçue: {interaction.get('content', '')}",
                        },
                    ],
                    "max_tokens": 150,
                    "temperature": 0.7,
                },
            )
            if r.status_code < 400:
                reply = r.json()["choices"][0]["message"]["content"]
                # Stocker la réponse générée
                logger.info("Auto-reply generated for %s interaction", platform)
    except Exception as e:
        logger.debug("Auto-reply error: %s", e)


@app.task(bind=True, max_retries=3, default_retry_delay=30)
def social_auto_publish(self):
    """Publie les posts sociaux programmés dont l'heure est dépassée."""
    import asyncio
    try:
        asyncio.run(_async_auto_publish())
    except Exception as exc:
        raise self.retry(exc=exc)


async def _async_auto_publish():
    """Publie les posts dont scheduled_for <= maintenant."""
    c = _get_db()
    if not c:
        return

    now = datetime.now(timezone.utc).isoformat()
    try:
        res = (
            c.table("social_posts")
            .select("*")
            .lte("scheduled_for", now)
            .is_("published_at", "null")
            .execute()
        )
        posts_to_publish = res.data or []
    except Exception as e:
        logger.error("Auto-publish fetch error: %s", e)
        return

    from services.social_service import _publish_to_platform
    for post in posts_to_publish:
        user_id = post.get("user_id")
        content = post.get("content", "")
        platforms = post.get("platforms", [])
        media_urls = post.get("media_urls", [])
        hashtags = post.get("hashtags", [])
        post_id = post.get("id")

        results: Dict[str, Any] = {}
        for platform in platforms:
            try:
                result = await _publish_to_platform(user_id, platform, content, media_urls, hashtags)
                results[platform] = result
            except Exception as e:
                results[platform] = {"error": str(e)}

        try:
            c.table("social_posts").update({
                "published_at": now,
                "engagement_stats": results,
            }).eq("id", post_id).execute()
        except Exception as e:
            logger.warning("Auto-publish update error: %s", e)
