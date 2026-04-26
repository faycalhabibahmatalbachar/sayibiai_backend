"""Journal d'usage — table usage_logs (Supabase) ou no-op."""

from typing import Any, Optional

from core.database import get_supabase_admin


async def log_usage(
    user_id: str,
    endpoint: str,
    tokens_used: Optional[int],
    model: Optional[str],
) -> None:
    """Insère une ligne d'usage si la table existe."""
    client = get_supabase_admin()
    if not client:
        return
    try:
        client.table("usage_logs").insert(
            {
                "user_id": user_id,
                "endpoint": endpoint,
                "tokens_used": tokens_used,
                "model_used": model,
            },
        ).execute()
    except Exception:
        pass
