"""Client Supabase — base de données et auth."""

from typing import Any, Optional

from supabase import Client, create_client

from core.config import get_settings
from core.redis_client import get_async_redis

_supabase: Optional[Client] = None
_supabase_admin: Optional[Client] = None


async def init_db() -> None:
    """Initialisation au démarrage : prépare les clients Supabase et Redis si configurés."""
    get_supabase()
    get_supabase_admin()
    await get_async_redis()


def get_supabase() -> Optional[Client]:
    """Client Supabase avec la clé anon (lecture/RLS selon policies)."""
    global _supabase
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_key:
        return None
    if _supabase is None:
        _supabase = create_client(settings.supabase_url, settings.supabase_key)
    return _supabase


def get_supabase_admin() -> Optional[Client]:
    """Client service role pour opérations serveur (si clé définie)."""
    global _supabase_admin
    settings = get_settings()
    key = settings.supabase_service_role_key or settings.supabase_key
    if not settings.supabase_url or not key:
        return None
    if _supabase_admin is None:
        _supabase_admin = create_client(settings.supabase_url, key)
    return _supabase_admin


async def run_supabase_query(
    table: str,
    operation: str,
    **kwargs: Any,
) -> Any:
    """
    Exécute une requête table via client admin si disponible.
    operation: select, insert, update, delete
    """
    client = get_supabase_admin() or get_supabase()
    if not client:
        raise RuntimeError("Supabase non configuré")
    table_ref = client.table(table)
    if operation == "select":
        q = table_ref.select(kwargs.get("columns", "*"))
        if kwargs.get("eq"):
            for col, val in kwargs["eq"].items():
                q = q.eq(col, val)
        if kwargs.get("order"):
            o = kwargs["order"]
            q = q.order(o["column"], desc=o.get("desc", False))
        if kwargs.get("limit"):
            q = q.limit(kwargs["limit"])
        return q.execute()
    if operation == "insert":
        return table_ref.insert(kwargs["data"]).execute()
    if operation == "update":
        q = table_ref.update(kwargs["data"])
        if kwargs.get("eq"):
            for col, val in kwargs["eq"].items():
                q = q.eq(col, val)
        return q.execute()
    if operation == "delete":
        q = table_ref.delete()
        if kwargs.get("eq"):
            for col, val in kwargs["eq"].items():
                q = q.eq(col, val)
        return q.execute()
    raise ValueError(f"Opération inconnue: {operation}")
