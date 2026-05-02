"""
ChadGPT Admin API Router — /api/v1/admin/*
Endpoints pour le panneau d'administration entreprise.
Utilise le client service_role (bypass RLS) pour accès complet aux données.
Authentification via JWT admin séparé du JWT utilisateur.
"""

import csv
import io
import json
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Request, Query, status, BackgroundTasks
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr

from core.config import get_settings
from core.database import get_supabase_admin
from core.responses import error_response, success_response
from core.security import create_access_token, get_subject_from_token
from services.user_intel_service import (
    apply_list_mask,
    compute_ml_profile,
    dispatch_user_webhooks_sync,
    load_active_webhooks,
    mask_email,
)
from services.admin_nl_heuristic import (
    assistant_reply,
    effective_user_list_params,
    parse_nl_user_query,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])
_bearer = HTTPBearer(auto_error=False)


def _unwrap_rpc_jsonb(payload: Any) -> Dict[str, Any]:
    """Normalise la réponse PostgREST d'un RPC JSONB (souvent `[{ fn_...: {...} }]`)."""
    if payload is None:
        return {}
    if isinstance(payload, dict) and ("stages" in payload or "period_days" in payload):
        return payload
    if isinstance(payload, list) and len(payload) > 0:
        row = payload[0]
        if not isinstance(row, dict):
            return {}
        for _k, val in row.items():
            if isinstance(val, dict) and ("stages" in val or "period_days" in val):
                return val
        return row
    return {}


# ─── Admin Auth Dependency ────────────────────────────────────────────────────

async def get_admin_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Dict[str, Any]:
    """
    Vérifie le JWT admin et retourne l'admin connecté.
    Le token doit avoir type='admin_access' dans son payload.
    """
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Admin token requis")

    settings = get_settings()
    sub = get_subject_from_token(credentials.credentials)
    if not sub:
        logger.warning(
            "Admin auth: Bearer présent mais subject absent (JWT invalide, expiré ou type incorrect)"
        )
        raise HTTPException(status_code=401, detail="Token admin invalide ou expiré")

    db = get_supabase_admin()
    if not db:
        raise HTTPException(status_code=503, detail="Base de données indisponible")

    res = db.table("admin_users").select("*").eq("id", sub).eq("is_active", True).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=401, detail="Compte admin non trouvé ou désactivé")

    return res.data[0]


def _db():
    return get_supabase_admin()


def _parse_tags_param(tags: Optional[str]) -> List[str]:
    if not tags:
        return []
    return [t.strip() for t in tags.split(",") if t.strip()]


def _user_ids_matching_all_tags(db: Any, tag_list: List[str]) -> Optional[Set[str]]:
    """AND logique sur les tags ; None si aucun filtre tag."""
    if not tag_list:
        return None
    sets: List[Set[str]] = []
    for t in tag_list:
        r = db.table("admin_user_tags").select("user_id").eq("tag", t).execute()
        sets.append({row["user_id"] for row in (r.data or [])})
    out = sets[0].copy()
    for s in sets[1:]:
        out &= s
    return out


def _search_or_clause(term: str) -> str:
    parts = [f"email.ilike.%{term}%", f"full_name.ilike.%{term}%"]
    if len(term) == 36 and term.count("-") == 4:
        parts.append(f"id.eq.{term}")
    return ",".join(parts)


def _apply_user_list_filters(q: Any, search: Optional[str], plan: Optional[str], status: Optional[str],
                             country_code: Optional[str], date_from: Optional[str], date_to: Optional[str],
                             tag_ids: Optional[Set[str]]) -> Any:
    if search:
        q = q.or_(_search_or_clause(search.strip()))
    if plan and plan != "all":
        q = q.eq("plan", plan)
    if status and status != "all":
        q = q.eq("status", status)
    if country_code:
        q = q.eq("country_code", country_code.strip().upper()[:2])
    if date_from:
        q = q.gte("created_at", date_from)
    if date_to:
        q = q.lte("created_at", date_to)
    if tag_ids is not None:
        q = q.in_("id", list(tag_ids)[:2000])
    return q


def _audit(admin: Dict, action: str, entity_type: str = None,
           entity_id: str = None, changes: Dict = None, request: Request = None):
    """Enregistre une action dans l'audit log."""
    try:
        db = _db()
        if not db:
            return
        log = {
            "admin_id": admin["id"],
            "admin_email": admin["email"],
            "action": action,
            "entity_type": entity_type,
            "entity_id": str(entity_id) if entity_id else None,
            "changes": changes or {},
            "ip_address": request.client.host if request and request.client else None,
            "user_agent": request.headers.get("user-agent") if request else None,
        }
        db.table("admin_audit_log").insert(log).execute()
    except Exception as e:
        logger.warning("Audit log failed: %s", e)


# ─── Models ───────────────────────────────────────────────────────────────────

class AdminLoginRequest(BaseModel):
    email: EmailStr
    password: str


class BanUserRequest(BaseModel):
    reason: str
    duration: Optional[str] = "permanent"  # "24h","7d","30d","permanent"


class ModerationDecisionRequest(BaseModel):
    decision: str  # approve, reject, warn, ban, escalate
    reason: Optional[str] = None


class BulkActionRequest(BaseModel):
    user_ids: List[str]
    action: str  # ban, unban, export, send_notification
    payload: Optional[Dict] = None


class UpdateUserRequest(BaseModel):
    plan: Optional[str] = None
    full_name: Optional[str] = None
    language: Optional[str] = None
    country_code: Optional[str] = None


class AdminNoteCreate(BaseModel):
    content: str


class AdminNoteUpdate(BaseModel):
    content: str


class UserActionRequest(BaseModel):
    action: str
    params: Optional[Dict[str, Any]] = None


class WebhookUpsertRequest(BaseModel):
    url: str
    events: List[str]
    secret: Optional[str] = None
    is_active: bool = True


class SettingUpdateRequest(BaseModel):
    value: Any
    description: Optional[str] = None


class NlSearchRequest(BaseModel):
    """Recherche utilisateurs en langage naturel (phase heuristique)."""

    query: str
    search: Optional[str] = None
    plan: Optional[str] = None
    status: Optional[str] = None
    country_code: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    tags: Optional[str] = None


class AssistantChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None


# ─── AUTH ─────────────────────────────────────────────────────────────────────

@router.post("/auth/login")
async def admin_login(body: AdminLoginRequest, request: Request):
    """
    Authentification admin — email + password.
    Retourne un JWT admin valide 8h.
    """
    import bcrypt as _bcrypt

    db = _db()
    if not db:
        return error_response("Base de données indisponible", 503)

    res = db.table("admin_users").select("*").eq("email", body.email).eq("is_active", True).limit(1).execute()
    if not res.data:
        # Timing-safe: still check password to prevent enumeration
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")

    admin = res.data[0]

    try:
        valid = _bcrypt.checkpw(body.password.encode("utf-8"), admin["password_hash"].encode("utf-8"))
    except Exception:
        valid = False

    if not valid:
        _audit(admin, "login_failed", "admin_users", admin["id"], request=request)
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")

    # Create admin JWT (8h expiry)
    settings = get_settings()
    token = create_access_token(admin["id"], {
        "email": admin["email"],
        "role": admin["role"],
        "type": "admin_access",
    })

    # Update last_login
    db.table("admin_users").update({
        "last_login_at": datetime.now(timezone.utc).isoformat(),
        "last_login_ip": request.client.host if request.client else None,
    }).eq("id", admin["id"]).execute()

    _audit(admin, "login_success", "admin_users", admin["id"], request=request)

    return success_response({
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 8 * 3600,
        "admin": {
            "id": admin["id"],
            "email": admin["email"],
            "full_name": admin["full_name"],
            "role": admin["role"],
            "permissions": admin.get("permissions", []),
        }
    }, "Connexion admin réussie")


@router.get("/auth/me")
async def admin_me(admin: Dict = Depends(get_admin_user)):
    """Retourne le profil de l'admin connecté."""
    return success_response({
        "id": admin["id"],
        "email": admin["email"],
        "full_name": admin["full_name"],
        "role": admin["role"],
        "permissions": admin.get("permissions", []),
        "two_fa_enabled": admin.get("two_fa_enabled", False),
        "last_login_at": admin.get("last_login_at"),
    })


# ─── DASHBOARD ────────────────────────────────────────────────────────────────

@router.get("/dashboard/kpis")
async def dashboard_kpis(admin: Dict = Depends(get_admin_user)):
    """
    KPIs temps réel du dashboard:
    utilisateurs, requêtes, tokens, latence, erreurs, modération.
    Source: function fn_dashboard_kpis() + vues agrégées.
    """
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)

    try:
        # Main KPIs via function
        kpi_res = db.rpc("fn_dashboard_kpis").execute()
        kpis = kpi_res.data if kpi_res.data else {}

        # Daily trend (last 30 days)
        trend_res = db.table("v_daily_stats").select("*").limit(30).execute()
        daily_trend = trend_res.data or []

        # Plan distribution
        plan_res = db.table("v_plan_distribution").select("*").execute()
        plans = plan_res.data or []

        # Real-time: last 60 minutes requests by minute
        from_ts = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        hour_res = db.table("usage_logs").select("created_at").gte("created_at", from_ts).execute()
        hour_data = hour_res.data or []

        return success_response({
            "kpis": kpis,
            "daily_trend": daily_trend,
            "plan_distribution": plans,
            "last_hour_requests": len(hour_data),
        })
    except Exception as e:
        logger.error("dashboard_kpis error: %s", e)
        return error_response(str(e), 500)


@router.get("/dashboard/realtime")
async def dashboard_realtime(admin: Dict = Depends(get_admin_user)):
    """Données temps réel: requêtes dernières 5 minutes."""
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    try:
        from_ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        res = db.table("usage_logs").select("created_at, status_code, request_duration_ms, model_used") \
            .gte("created_at", from_ts).order("created_at", desc=True).limit(500).execute()
        logs = res.data or []

        # Group by minute
        by_minute: Dict[str, Dict] = {}
        for log in logs:
            ts = log["created_at"][:16]  # YYYY-MM-DDTHH:MM
            if ts not in by_minute:
                by_minute[ts] = {"time": ts, "requests": 0, "errors": 0, "avg_latency": 0, "_lat": []}
            by_minute[ts]["requests"] += 1
            if (log.get("status_code") or 200) >= 400:
                by_minute[ts]["errors"] += 1
            if log.get("request_duration_ms"):
                by_minute[ts]["_lat"].append(log["request_duration_ms"])

        result = []
        for ts, v in sorted(by_minute.items()):
            v["avg_latency"] = int(sum(v["_lat"]) / len(v["_lat"])) if v["_lat"] else 0
            del v["_lat"]
            result.append(v)

        return success_response({"datapoints": result, "total": len(logs)})
    except Exception as e:
        logger.error("realtime error: %s", e)
        return error_response(str(e), 500)


# ─── USERS ────────────────────────────────────────────────────────────────────

@router.get("/users")
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    search: Optional[str] = Query(None),
    plan: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    country_code: Optional[str] = Query(None),
    tags: Optional[str] = Query(None, description="Tags séparés par virgule (AND)"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    sort: Optional[str] = Query("created_at"),
    order: Optional[str] = Query("desc"),
    cursor: Optional[str] = Query(None, description="UUID — pagination curseur (sort=id)"),
    admin: Dict = Depends(get_admin_user),
):
    """
    Liste paginée (offset ou curseur sur `id`), emails masqués, filtres étendus.
    """
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)

    try:
        valid_sorts = {"created_at", "email", "plan", "total_tokens_used", "requests_today", "id", "risk_score"}
        sort_col = sort if sort in valid_sorts else "created_at"
        sort_desc = order.lower() != "asc"
        tag_list = _parse_tags_param(tags)
        tag_ids = _user_ids_matching_all_tags(db, tag_list)
        if tag_ids is not None and len(tag_ids) == 0:
            return success_response({
                "users": [],
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total": 0,
                    "total_pages": 1,
                    "next_cursor": None,
                    "has_more": False,
                    "mode": "offset",
                },
                "stats": {},
            })

        stats = {}
        try:
            kpi_res = db.rpc("fn_dashboard_kpis").execute()
            stats = kpi_res.data if isinstance(kpi_res.data, dict) else {}
        except Exception:
            pass

        use_cursor = bool(cursor and sort_col == "id")
        q = _apply_user_list_filters(
            db.table("v_admin_users_full").select("*"),
            search, plan, status, country_code, date_from, date_to, tag_ids,
        )
        if use_cursor:
            q = q.lt("id", cursor)
            q = q.order("id", desc=True).limit(page_size)
            res = q.execute()
            users = res.data or []
            next_c = users[-1]["id"] if len(users) == page_size and users else None
            return success_response({
                "users": apply_list_mask(users),
                "pagination": {
                    "page": 1,
                    "page_size": page_size,
                    "total": None,
                    "total_pages": None,
                    "next_cursor": next_c,
                    "has_more": len(users) == page_size,
                    "mode": "cursor",
                },
                "stats": stats,
            })

        count_q = _apply_user_list_filters(
            db.table("v_admin_users_full").select("id", count="exact"),
            search, plan, status, country_code, date_from, date_to, tag_ids,
        )
        count_res = count_q.execute()
        total = count_res.count or 0

        offset = (page - 1) * page_size
        q = _apply_user_list_filters(
            db.table("v_admin_users_full").select("*"),
            search, plan, status, country_code, date_from, date_to, tag_ids,
        )
        q = q.order(sort_col, desc=sort_desc).range(offset, offset + page_size - 1)
        res = q.execute()
        users = res.data or []

        return success_response({
            "users": apply_list_mask(users),
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": ceil(total / page_size) if total else 1,
                "next_cursor": None,
                "has_more": offset + len(users) < total,
                "mode": "offset",
            },
            "stats": stats,
        })
    except Exception as e:
        logger.error("list_users error: %s", e)
        return error_response(str(e), 500)


@router.post("/users/nl-search")
async def nl_search_users(
    body: NlSearchRequest,
    request: Request,
    admin: Dict = Depends(get_admin_user),
):
    """
    Interprète une phrase (FR/EN) en filtres + compte les utilisateurs correspondants.
    Journalise dans admin_nl_search_log si la table existe.
    """
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)

    t0 = time.perf_counter()
    parsed = parse_nl_user_query(body.query)
    parsed_public = {k: v for k, v in parsed.items() if not str(k).startswith("_")}
    eff = effective_user_list_params(
        parsed,
        search=body.search,
        plan=body.plan,
        status=body.status,
        country_code=body.country_code,
        date_from=body.date_from,
        date_to=body.date_to,
        tags=body.tags,
    )
    tag_list = _parse_tags_param(eff.get("tags"))
    tag_ids = _user_ids_matching_all_tags(db, tag_list)
    if tag_ids is not None and len(tag_ids) == 0:
        ms = int((time.perf_counter() - t0) * 1000)
        _log_nl_search(db, admin, body.query, parsed_public, 0, ms)
        return success_response(
            {
                "parsed_filters": parsed_public,
                "effective_filters": {k: v for k, v in eff.items() if v},
                "result_count": 0,
                "latency_ms": ms,
                "model_version": "heuristic_nl_v1",
            }
        )

    try:
        count_q = _apply_user_list_filters(
            db.table("v_admin_users_full").select("id", count="exact"),
            eff.get("search"),
            eff.get("plan"),
            eff.get("status"),
            eff.get("country_code"),
            eff.get("date_from"),
            eff.get("date_to"),
            tag_ids,
        )
        count_res = count_q.execute()
        total = count_res.count or 0
    except Exception as e:
        logger.error("nl_search_users count error: %s", e)
        return error_response(str(e), 500)

    ms = int((time.perf_counter() - t0) * 1000)
    _log_nl_search(db, admin, body.query, {**parsed_public, **{k: v for k, v in eff.items() if v}}, total, ms)

    return success_response(
        {
            "parsed_filters": parsed_public,
            "effective_filters": {k: v for k, v in eff.items() if v},
            "result_count": total,
            "latency_ms": ms,
            "model_version": "heuristic_nl_v1",
            "notes": parsed.get("_nl_note"),
        }
    )


def _log_nl_search(db: Any, admin: Dict, query_text: str, parsed: Dict, result_count: int, latency_ms: int) -> None:
    try:
        db.table("admin_nl_search_log").insert(
            {
                "admin_id": admin.get("id"),
                "query_text": query_text[:4000],
                "parsed_filters": parsed,
                "result_count": result_count,
                "latency_ms": latency_ms,
                "model_version": "heuristic_nl_v1",
            }
        ).execute()
    except Exception as e:
        logger.warning("admin_nl_search_log insert skipped: %s", e)


@router.post("/assistant/chat")
async def admin_assistant_chat(
    body: AssistantChatRequest,
    admin: Dict = Depends(get_admin_user),
):
    """
    Assistant guidage (sans LLM) : réponses basées sur routes + KPIs réels si disponibles.
    """
    db = _db()
    kpis: Dict[str, Any] = {}
    if db:
        try:
            kpi_res = db.rpc("fn_dashboard_kpis").execute()
            raw = kpi_res.data
            if isinstance(raw, dict):
                inner = raw.get("kpis")
                kpis = inner if isinstance(inner, dict) else raw
            elif isinstance(raw, list) and raw and isinstance(raw[0], dict):
                row = raw[0]
                inner = row.get("kpis")
                kpis = inner if isinstance(inner, dict) else row
        except Exception as e:
            logger.debug("assistant_chat KPI optional: %s", e)

    out = assistant_reply(body.message, kpis=kpis or None)
    _audit(
        admin,
        "assistant_chat",
        "admin_assistant",
        body.conversation_id,
        {"message_len": len(body.message or "")},
        None,
    )
    return success_response(out)


@router.get("/users/{user_id}")
async def get_user(user_id: str, admin: Dict = Depends(get_admin_user)):
    """
    Détail complet d'un utilisateur 360°.
    Inclut sessions, messages, documents, usage, flags de modération.
    """
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)

    try:
        # User from view
        user_res = db.table("v_admin_users_full").select("*").eq("id", user_id).limit(1).execute()
        if not user_res.data:
            return error_response("Utilisateur introuvable", 404)
        user = user_res.data[0]

        # Last 10 sessions
        sessions_res = db.table("chat_sessions").select("id, title, model_used, total_messages, total_tokens, created_at") \
            .eq("user_id", user_id).order("created_at", desc=True).limit(10).execute()

        # Last 20 usage logs
        usage_res = db.table("usage_logs").select("endpoint, model_used, tokens_used, request_duration_ms, status_code, created_at") \
            .eq("user_id", user_id).order("created_at", desc=True).limit(20).execute()

        # Daily usage last 30 days
        daily_res = db.table("usage_logs") \
            .select("created_at").eq("user_id", user_id) \
            .gte("created_at", (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()) \
            .execute()

        # Moderation flags
        flags_res = db.table("moderation_queue").select("*") \
            .eq("user_id", user_id).order("flagged_at", desc=True).limit(10).execute()

        # Documents
        docs_res = db.table("documents").select("id, filename, file_type, file_size, created_at") \
            .eq("user_id", user_id).order("created_at", desc=True).limit(10).execute()

        tags_list: List[Dict] = []
        notes_list: List[Dict] = []
        ml_row: Optional[Dict] = None
        try:
            tags_list = (db.table("admin_user_tags").select("tag, tagged_at, tagged_by")
                         .eq("user_id", user_id).execute()).data or []
        except Exception:
            pass
        try:
            notes_list = (db.table("admin_user_notes").select("id, content, admin_id, created_at, updated_at")
                          .eq("user_id", user_id).order("created_at", desc=True).limit(30).execute()).data or []
        except Exception:
            pass
        try:
            ml_r = db.table("user_ml_profiles").select("*").eq("user_id", user_id).limit(1).execute()
            ml_row = ml_r.data[0] if ml_r.data else None
        except Exception:
            pass

        predictions = compute_ml_profile(user)
        scores = {
            "engagement_score": predictions["engagement_score"],
            "churn_risk": predictions["churn_risk"],
            "upsell_propensity": predictions.get("upsell_propensity"),
            "ltv_estimate_usd": predictions.get("ltv_estimate_usd"),
            "health_label": predictions.get("health_label"),
            "cached_profile": ml_row,
        }

        return success_response({
            "user": user,
            "recent_sessions": sessions_res.data or [],
            "recent_usage": usage_res.data or [],
            "daily_requests_30d": len(daily_res.data or []),
            "moderation_flags": flags_res.data or [],
            "documents": docs_res.data or [],
            "tags": tags_list,
            "admin_notes": notes_list,
            "scores": scores,
            "predictions": predictions,
        })
    except Exception as e:
        logger.error("get_user error: %s", e)
        return error_response(str(e), 500)


@router.get("/users/{user_id}/activity")
async def get_user_activity(
    user_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(40, ge=1, le=100),
    admin: Dict = Depends(get_admin_user),
):
    """Timeline agrégée : usage_logs + entrées modération récentes."""
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    try:
        chk = db.table("v_admin_users_full").select("id").eq("id", user_id).limit(1).execute()
        if not chk.data:
            return error_response("Utilisateur introuvable", 404)
        offset = (page - 1) * limit
        ul = db.table("usage_logs").select(
            "id, endpoint, model_used, tokens_used, request_duration_ms, status_code, created_at"
        ).eq("user_id", user_id).order("created_at", desc=True).range(offset, offset + limit - 1).execute()
        events = []
        for row in ul.data or []:
            events.append({
                "type": "api_request",
                "at": row.get("created_at"),
                "title": row.get("endpoint") or "request",
                "detail": {
                    "model_used": row.get("model_used"),
                    "tokens_used": row.get("tokens_used"),
                    "status_code": row.get("status_code"),
                },
            })
        mq = db.table("moderation_queue").select("id, status, content_preview, flagged_at, decision_reason") \
            .eq("user_id", user_id).order("flagged_at", desc=True).limit(15).execute()
        for row in mq.data or []:
            events.append({
                "type": "moderation",
                "at": row.get("flagged_at"),
                "title": f"Moderation: {row.get('status')}",
                "detail": {"preview": (row.get("content_preview") or "")[:200], "reason": row.get("decision_reason")},
            })
        events.sort(key=lambda x: (x.get("at") or ""), reverse=True)
        return success_response({"events": events[:limit], "page": page})
    except Exception as e:
        logger.error("get_user_activity error: %s", e)
        return error_response(str(e), 500)


@router.get("/users/{user_id}/media")
async def get_user_media(
    user_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(24, ge=1, le=100),
    admin: Dict = Depends(get_admin_user),
):
    """Fichiers générés + images (deux sources)."""
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    try:
        chk = db.table("users").select("id").eq("id", user_id).limit(1).execute()
        if not chk.data:
            return error_response("Utilisateur introuvable", 404)
        offset = (page - 1) * limit
        files = db.table("generated_files").select("id, file_type, filename, prompt_used, created_at") \
            .eq("user_id", user_id).order("created_at", desc=True).range(offset, offset + limit - 1).execute()
        imgs = db.table("generated_images").select(
            "id, original_prompt, image_url, watermarked_url, generation_cost, created_at"
        ).eq("user_id", user_id).order("created_at", desc=True).range(0, limit - 1).execute()
        items = []
        for f in files.data or []:
            items.append({"kind": "file", **f})
        for im in imgs.data or []:
            items.append({
                "kind": "image",
                "id": im.get("id"),
                "prompt": im.get("original_prompt"),
                "url": im.get("watermarked_url") or im.get("image_url"),
                "cost": im.get("generation_cost"),
                "created_at": im.get("created_at"),
            })
        items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
        return success_response({"items": items[:limit], "page": page})
    except Exception as e:
        logger.error("get_user_media error: %s", e)
        return error_response(str(e), 500)


@router.get("/users/{user_id}/notes")
async def list_user_notes(user_id: str, admin: Dict = Depends(get_admin_user)):
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    try:
        res = db.table("admin_user_notes").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
        return success_response({"notes": res.data or []})
    except Exception as e:
        logger.error("list_user_notes error: %s", e)
        return error_response(str(e), 500)


@router.post("/users/{user_id}/notes")
async def create_user_note(
    user_id: str,
    body: AdminNoteCreate,
    request: Request,
    admin: Dict = Depends(get_admin_user),
):
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    try:
        row = {
            "user_id": user_id,
            "admin_id": admin["id"],
            "content": body.content,
        }
        res = db.table("admin_user_notes").insert(row).execute()
        _audit(admin, "user_note_create", "users", user_id, {}, request)
        return success_response(res.data[0] if res.data else row, "Note créée")
    except Exception as e:
        logger.error("create_user_note error: %s", e)
        return error_response(str(e), 500)


@router.put("/users/{user_id}/notes/{note_id}")
async def update_user_note(
    user_id: str,
    note_id: str,
    body: AdminNoteUpdate,
    request: Request,
    admin: Dict = Depends(get_admin_user),
):
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    try:
        res = db.table("admin_user_notes").update({"content": body.content, "updated_at": datetime.now(timezone.utc).isoformat()}) \
            .eq("id", note_id).eq("user_id", user_id).execute()
        _audit(admin, "user_note_update", "users", user_id, {"note_id": note_id}, request)
        return success_response(res.data[0] if res.data else {}, "Note mise à jour")
    except Exception as e:
        logger.error("update_user_note error: %s", e)
        return error_response(str(e), 500)


@router.post("/users/{user_id}/tags")
async def add_user_tag(
    user_id: str,
    request: Request,
    tag: str = Query(..., min_length=1, max_length=64),
    admin: Dict = Depends(get_admin_user),
):
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    try:
        row = {"user_id": user_id, "tag": tag.strip(), "tagged_by": admin["id"]}
        db.table("admin_user_tags").upsert(row).execute()
        _audit(admin, "user_tag_add", "users", user_id, {"tag": tag}, request)
        hooks = load_active_webhooks(db)
        dispatch_user_webhooks_sync(hooks, "user.tagged", {"user_id": user_id, "tag": tag})
        return success_response(row, "Tag ajouté")
    except Exception as e:
        logger.error("add_user_tag error: %s", e)
        return error_response(str(e), 500)


@router.delete("/users/{user_id}/tags/{tag}")
async def remove_user_tag(
    user_id: str,
    tag: str,
    request: Request,
    admin: Dict = Depends(get_admin_user),
):
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    try:
        db.table("admin_user_tags").delete().eq("user_id", user_id).eq("tag", tag).execute()
        _audit(admin, "user_tag_remove", "users", user_id, {"tag": tag}, request)
        return success_response({"removed": True})
    except Exception as e:
        logger.error("remove_user_tag error: %s", e)
        return error_response(str(e), 500)


@router.post("/users/{user_id}/actions")
async def user_actions(
    user_id: str,
    body: UserActionRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    admin: Dict = Depends(get_admin_user),
):
    """Actions unifiées : change_plan, offer_credits (audit), send_email (stub), delete_data, ban."""
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    params = body.params or {}
    try:
        if body.action == "change_plan":
            plan = params.get("plan", "free")
            db.table("users").update({"plan": plan}).eq("id", user_id).execute()
            _audit(admin, "user_action_change_plan", "users", user_id, {"plan": plan}, request)
        elif body.action == "offer_credits":
            _audit(admin, "user_action_offer_credits", "users", user_id, params, request)
        elif body.action == "send_email":
            _audit(admin, "user_action_send_email", "users", user_id, params, request)
        elif body.action == "ban":
            reason = params.get("reason", "admin")
            db.table("moderation_queue").insert({
                "user_id": user_id,
                "content_type": "text",
                "content_preview": f"[BAN ADMIN] Raison: {reason}",
                "ai_scores": {},
                "ai_confidence": 100,
                "priority": 100,
                "status": "banned",
                "reviewed_by": admin["id"],
                "decision_reason": reason,
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
            _audit(admin, "ban_user", "users", user_id, {"reason": reason}, request)
        elif body.action == "delete_data":
            if admin["role"] not in ("super_admin", "admin"):
                return error_response("Permissions insuffisantes", 403)
            for tbl in (
                "usage_logs", "notifications", "generated_files", "documents", "moderation_queue",
                "admin_user_notes", "admin_user_tags", "user_ml_profiles",
            ):
                try:
                    db.table(tbl).delete().eq("user_id", user_id).execute()
                except Exception:
                    pass
            try:
                db.table("generated_images").delete().eq("user_id", user_id).execute()
            except Exception:
                pass
            db.table("chat_sessions").delete().eq("user_id", user_id).execute()
            _audit(admin, "delete_user_data", "users", user_id, {}, request)
        else:
            return error_response(f"Action inconnue: {body.action}", 400)

        hooks = load_active_webhooks(db)
        background_tasks.add_task(
            dispatch_user_webhooks_sync,
            hooks,
            "user.action",
            {"user_id": user_id, "action": body.action, "params": params},
        )
        return success_response({"ok": True}, "Action exécutée")
    except Exception as e:
        logger.error("user_actions error: %s", e)
        return error_response(str(e), 500)


@router.get("/users-export/stream")
async def export_users_stream(
    format: str = Query("csv", pattern="^(csv|json)$"),
    plan: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    admin: Dict = Depends(get_admin_user),
):
    """Export paginé en flux (pas de chargement millions de lignes d’un coup)."""
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    batch = 500
    max_rows = 100_000

    def row_iter():
        offset = 0
        n = 0
        while n < max_rows:
            q = db.table("v_admin_users_full").select(
                "id, email, full_name, plan, status, country_code, created_at, total_tokens_used, risk_score"
            )
            if plan and plan != "all":
                q = q.eq("plan", plan)
            if status and status != "all":
                q = q.eq("status", status)
            chunk = q.order("created_at", desc=True).range(offset, offset + batch - 1).execute()
            rows = chunk.data or []
            if not rows:
                break
            for u in rows:
                u = dict(u)
                u["email"] = mask_email(u.get("email"))
                yield u
            n += len(rows)
            offset += batch
            if len(rows) < batch:
                break

    if format == "json":

        def gen_json():
            yield "["
            first = True
            for u in row_iter():
                if not first:
                    yield ","
                first = False
                yield json.dumps(u, default=str)
            yield "]"

        return StreamingResponse(gen_json(), media_type="application/json", headers={
            "Content-Disposition": 'attachment; filename="users_export.json"',
        })

    def gen_csv():
        buf = io.StringIO()
        writer: Optional[csv.DictWriter] = None
        for u in row_iter():
            if writer is None:
                writer = csv.DictWriter(buf, fieldnames=list(u.keys()))
                writer.writeheader()
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate(0)
            writer.writerow(u)
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    return StreamingResponse(gen_csv(), media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": 'attachment; filename="users_export.csv"',
    })


@router.get("/webhooks")
async def list_webhooks(admin: Dict = Depends(get_admin_user)):
    if admin["role"] not in ("super_admin", "admin"):
        return error_response("Accès refusé", 403)
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    try:
        res = db.table("admin_webhooks").select("id, url, events, is_active, created_at").execute()
        return success_response({"webhooks": res.data or []})
    except Exception as e:
        return error_response(str(e), 500)


@router.post("/webhooks")
async def create_webhook(
    body: WebhookUpsertRequest,
    request: Request,
    admin: Dict = Depends(get_admin_user),
):
    if admin["role"] not in ("super_admin", "admin"):
        return error_response("Accès refusé", 403)
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    try:
        row = {
            "url": body.url,
            "events": body.events,
            "secret": body.secret,
            "is_active": body.is_active,
            "created_by": admin["id"],
        }
        res = db.table("admin_webhooks").insert(row).execute()
        _audit(admin, "webhook_create", "admin_webhooks", res.data[0]["id"] if res.data else None, {}, request)
        return success_response(res.data[0] if res.data else row)
    except Exception as e:
        return error_response(str(e), 500)


@router.put("/users/{user_id}")
async def update_user(
    user_id: str,
    body: UpdateUserRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    admin: Dict = Depends(get_admin_user),
):
    """Met à jour le profil ou le plan d'un utilisateur."""
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    try:
        update_data = {k: v for k, v in body.model_dump().items() if v is not None}
        if not update_data:
            return error_response("Aucune donnée à mettre à jour", 400)
        res = db.table("users").update(update_data).eq("id", user_id).execute()
        _audit(admin, "update_user", "users", user_id, {"changes": update_data}, request)
        urow = res.data[0] if res.data else {"id": user_id, **update_data}
        hooks = load_active_webhooks(db)
        background_tasks.add_task(dispatch_user_webhooks_sync, hooks, "user.updated", {"user": urow})
        return success_response(urow, "Utilisateur mis à jour")
    except Exception as e:
        logger.error("update_user error: %s", e)
        return error_response(str(e), 500)


@router.post("/users/{user_id}/ban")
async def ban_user(
    user_id: str,
    body: BanUserRequest,
    request: Request,
    admin: Dict = Depends(get_admin_user),
):
    """
    Ajoute un flag ban dans moderation_queue.
    Enregistre dans l'audit log.
    """
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    try:
        # Add ban to moderation queue
        ban_entry = {
            "user_id": user_id,
            "content_type": "text",
            "content_preview": f"[BAN ADMIN] Raison: {body.reason}",
            "ai_scores": {},
            "ai_confidence": 100,
            "priority": 100,
            "status": "banned",
            "reviewed_by": admin["id"],
            "decision_reason": body.reason,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        }
        db.table("moderation_queue").insert(ban_entry).execute()
        _audit(admin, "ban_user", "users", user_id, {"reason": body.reason, "duration": body.duration}, request)
        return success_response({"banned": True, "user_id": user_id}, f"Utilisateur banni: {body.reason}")
    except Exception as e:
        logger.error("ban_user error: %s", e)
        return error_response(str(e), 500)


@router.delete("/users/{user_id}/data")
async def delete_user_data(
    user_id: str,
    request: Request,
    admin: Dict = Depends(get_admin_user),
):
    """Supprime toutes les données d'un utilisateur (RGPD)."""
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    if admin["role"] not in ("super_admin", "admin"):
        return error_response("Permissions insuffisantes", 403)
    try:
        db.table("usage_logs").delete().eq("user_id", user_id).execute()
        db.table("notifications").delete().eq("user_id", user_id).execute()
        db.table("generated_files").delete().eq("user_id", user_id).execute()
        db.table("documents").delete().eq("user_id", user_id).execute()
        db.table("moderation_queue").delete().eq("user_id", user_id).execute()
        for tbl in ("admin_user_notes", "admin_user_tags", "user_ml_profiles"):
            try:
                db.table(tbl).delete().eq("user_id", user_id).execute()
            except Exception:
                pass
        try:
            db.table("generated_images").delete().eq("user_id", user_id).execute()
        except Exception:
            pass
        db.table("chat_sessions").delete().eq("user_id", user_id).execute()
        _audit(admin, "delete_user_data", "users", user_id, {}, request)
        return success_response({"deleted": True}, "Données utilisateur supprimées (RGPD)")
    except Exception as e:
        logger.error("delete_user_data error: %s", e)
        return error_response(str(e), 500)


@router.post("/users/bulk")
async def bulk_action(
    body: BulkActionRequest,
    request: Request,
    admin: Dict = Depends(get_admin_user),
):
    """Actions en masse sur plusieurs utilisateurs."""
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    results = {"processed": 0, "failed": 0, "errors": []}
    try:
        for uid in body.user_ids:
            try:
                if body.action == "ban":
                    reason = (body.payload or {}).get("reason", "Bulk ban")
                    db.table("moderation_queue").insert({
                        "user_id": uid,
                        "content_type": "text",
                        "content_preview": f"[BULK BAN] {reason}",
                        "ai_scores": {},
                        "ai_confidence": 100,
                        "priority": 100,
                        "status": "banned",
                        "reviewed_by": admin["id"],
                        "decision_reason": reason,
                        "reviewed_at": datetime.now(timezone.utc).isoformat(),
                    }).execute()
                elif body.action == "change_plan":
                    plan = (body.payload or {}).get("plan", "free")
                    db.table("users").update({"plan": plan}).eq("id", uid).execute()
                results["processed"] += 1
            except Exception as e:
                results["failed"] += 1
                results["errors"].append(str(e))
        _audit(admin, f"bulk_{body.action}", "users", None, {"count": len(body.user_ids)}, request)
        return success_response(results, f"Action '{body.action}' appliquée")
    except Exception as e:
        logger.error("bulk_action error: %s", e)
        return error_response(str(e), 500)


# ─── ANALYTICS ────────────────────────────────────────────────────────────────

@router.get("/analytics/daily")
async def analytics_daily(
    days: int = Query(30, ge=1, le=365),
    admin: Dict = Depends(get_admin_user),
):
    """Statistiques journalières: requêtes, utilisateurs actifs distincts, tokens, erreurs (fn_daily_stats)."""
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    try:
        res = db.rpc("fn_daily_stats", {"p_days": days}).execute()
        rows = res.data or []
        return success_response({"data": rows, "days": days})
    except Exception as e:
        logger.error("analytics_daily error: %s", e)
        return error_response(str(e), 500)


@router.get("/analytics/cohorts")
async def analytics_cohorts(
    months: int = Query(6, ge=1, le=12),
    admin: Dict = Depends(get_admin_user),
):
    """Analyse de rétention par cohorte mensuelle."""
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    try:
        res = db.rpc("fn_user_cohort_retention", {"p_months": months}).execute()
        return success_response({"cohorts": res.data or [], "months": months})
    except Exception as e:
        logger.error("analytics_cohorts error: %s", e)
        return error_response(str(e), 500)


@router.get("/analytics/funnel")
async def analytics_funnel(
    days: int = Query(30, ge=1, le=366),
    admin: Dict = Depends(get_admin_user),
):
    """Funnel de conversion (SQL fn_analytics_funnel — utilisateurs distincts)."""
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    try:
        res = db.rpc("fn_analytics_funnel", {"p_days": days}).execute()
        payload = _unwrap_rpc_jsonb(res.data)
        if not payload.get("stages"):
            payload = {"period_days": days, "stages": []}
        return success_response(payload)
    except Exception as e:
        logger.error("analytics_funnel error: %s", e)
        return error_response(str(e), 500)


@router.get("/analytics/geo")
async def analytics_geo(admin: Dict = Depends(get_admin_user)):
    """Répartition par langue et par pays (country_code sur users)."""
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    try:
        res = db.table("users").select("language, country_code").execute()
        data = res.data or []
        lang_count: Dict[str, int] = {}
        country_count: Dict[str, int] = {}
        for row in data:
            lang = row.get("language", "fr") or "fr"
            lang_count[lang] = lang_count.get(lang, 0) + 1
            raw_cc = row.get("country_code")
            if raw_cc is None:
                continue
            cc = str(raw_cc).strip().upper()
            if len(cc) == 2 and cc.isalpha():
                country_count[cc] = country_count.get(cc, 0) + 1

        by_lang = [{"language": k, "count": v} for k, v in sorted(lang_count.items(), key=lambda x: -x[1])]
        by_country = [{"country": k, "count": v} for k, v in sorted(country_count.items(), key=lambda x: -x[1])]
        return success_response({
            "by_language": by_lang,
            "by_country": by_country,
            "total": len(data),
        })
    except Exception as e:
        logger.error("analytics_geo error: %s", e)
        return error_response(str(e), 500)


# ─── MODELS ───────────────────────────────────────────────────────────────────

@router.get("/models/stats")
async def models_stats(admin: Dict = Depends(get_admin_user)):
    """
    Statistiques réelles de tous les modèles IA utilisés.
    Source: vue v_model_stats (usage_logs regroupé par model_used).
    """
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    try:
        res = db.table("v_model_stats").select("*").execute()
        return success_response({"models": res.data or []})
    except Exception as e:
        logger.error("models_stats error: %s", e)
        return error_response(str(e), 500)


@router.get("/models/endpoints")
async def endpoint_stats(admin: Dict = Depends(get_admin_user)):
    """Performance réelle de chaque endpoint API (latence P95, error rate)."""
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    try:
        res = db.table("v_endpoint_stats").select("*").execute()
        return success_response({"endpoints": res.data or []})
    except Exception as e:
        logger.error("endpoint_stats error: %s", e)
        return error_response(str(e), 500)


@router.get("/models/usage-trend")
async def model_usage_trend(
    model: str = Query(None),
    days: int = Query(7, ge=1, le=30),
    admin: Dict = Depends(get_admin_user),
):
    """Tendance d'utilisation d'un modèle sur N jours."""
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    try:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        q = db.table("usage_logs").select("created_at, model_used, tokens_used, request_duration_ms, status_code") \
            .gte("created_at", since)
        if model:
            q = q.eq("model_used", model)
        res = q.execute()
        data = res.data or []

        by_day: Dict[str, Dict] = {}
        for log in data:
            day = log["created_at"][:10]
            mdl = log.get("model_used") or "unknown"
            key = f"{day}|{mdl}"
            if key not in by_day:
                by_day[key] = {"date": day, "model": mdl, "requests": 0, "tokens": 0, "errors": 0}
            by_day[key]["requests"] += 1
            by_day[key]["tokens"] += log.get("tokens_used") or 0
            if (log.get("status_code") or 200) >= 400:
                by_day[key]["errors"] += 1

        return success_response({"trend": sorted(by_day.values(), key=lambda x: x["date"])})
    except Exception as e:
        logger.error("model_usage_trend error: %s", e)
        return error_response(str(e), 500)


# ─── MODERATION ───────────────────────────────────────────────────────────────

@router.get("/moderation/queue")
async def moderation_queue(
    status_filter: str = Query("pending"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    content_type: Optional[str] = Query(None),
    admin: Dict = Depends(get_admin_user),
):
    """
    File de modération avec pagination et filtres.
    Triée par priorité décroissante puis date croissante (plus ancien en premier).
    """
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    try:
        q = db.table("moderation_queue").select(
            "*, users(email, full_name, plan, total_tokens_used)"
        )
        if status_filter != "all":
            q = q.eq("status", status_filter)
        if content_type:
            q = q.eq("content_type", content_type)

        count_q = db.table("moderation_queue").select("id", count="exact")
        if status_filter != "all":
            count_q = count_q.eq("status", status_filter)
        count_res = count_q.execute()
        total = count_res.count or 0

        offset = (page - 1) * page_size
        q = q.order("priority", desc=True).order("flagged_at", desc=False) \
             .range(offset, offset + page_size - 1)
        res = q.execute()

        return success_response({
            "items": res.data or [],
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": ceil(total / page_size) if total else 1,
            }
        })
    except Exception as e:
        logger.error("moderation_queue error: %s", e)
        return error_response(str(e), 500)


@router.post("/moderation/{item_id}/decide")
async def moderation_decide(
    item_id: str,
    body: ModerationDecisionRequest,
    request: Request,
    admin: Dict = Depends(get_admin_user),
):
    """
    Décision de modération: approve, reject, warn, ban, escalate.
    Met à jour moderation_queue et enregistre dans l'audit log.
    """
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)

    valid_decisions = {"approve", "reject", "warn", "ban", "escalate"}
    if body.decision not in valid_decisions:
        return error_response(f"Décision invalide. Options: {valid_decisions}", 400)

    try:
        update = {
            "status": body.decision if body.decision != "warn" else "approved",
            "reviewed_by": admin["id"],
            "decision_reason": body.reason,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        }
        if body.decision == "warn":
            update["status"] = "approved"  # content approved but user warned

        db.table("moderation_queue").update(update).eq("id", item_id).execute()

        # If ban, add a ban entry for this user
        if body.decision == "ban":
            item_res = db.table("moderation_queue").select("user_id").eq("id", item_id).limit(1).execute()
            if item_res.data:
                user_id = item_res.data[0]["user_id"]
                # Add full ban entry
                db.table("moderation_queue").insert({
                    "user_id": user_id,
                    "content_type": "text",
                    "content_preview": f"[BAN par {admin['email']}] {body.reason}",
                    "ai_scores": {},
                    "ai_confidence": 100,
                    "priority": 100,
                    "status": "banned",
                    "reviewed_by": admin["id"],
                    "decision_reason": body.reason,
                    "reviewed_at": datetime.now(timezone.utc).isoformat(),
                }).execute()

        _audit(admin, f"moderation_{body.decision}", "moderation_queue", item_id,
               {"decision": body.decision, "reason": body.reason}, request)

        return success_response({"item_id": item_id, "decision": body.decision}, "Décision enregistrée")
    except Exception as e:
        logger.error("moderation_decide error: %s", e)
        return error_response(str(e), 500)


@router.get("/moderation/stats")
async def moderation_stats(admin: Dict = Depends(get_admin_user)):
    """Statistiques de modération: volume, répartition, temps moyen."""
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    try:
        all_res = db.table("moderation_queue").select("status, content_type, flagged_at, reviewed_at").execute()
        items = all_res.data or []

        by_status: Dict[str, int] = {}
        by_type: Dict[str, int] = {}
        review_times = []

        for item in items:
            s = item.get("status", "pending")
            by_status[s] = by_status.get(s, 0) + 1
            ct = item.get("content_type", "text")
            by_type[ct] = by_type.get(ct, 0) + 1
            if item.get("reviewed_at") and item.get("flagged_at"):
                try:
                    flagged = datetime.fromisoformat(item["flagged_at"].replace("Z", "+00:00"))
                    reviewed = datetime.fromisoformat(item["reviewed_at"].replace("Z", "+00:00"))
                    delta = (reviewed - flagged).total_seconds()
                    if 0 < delta < 86400:
                        review_times.append(delta)
                except Exception:
                    pass

        avg_time = int(sum(review_times) / len(review_times)) if review_times else 0

        return success_response({
            "total": len(items),
            "by_status": by_status,
            "by_content_type": by_type,
            "avg_review_time_seconds": avg_time,
            "pending": by_status.get("pending", 0),
        })
    except Exception as e:
        logger.error("moderation_stats error: %s", e)
        return error_response(str(e), 500)


# ─── BILLING / REVENUE ────────────────────────────────────────────────────────

@router.get("/billing/overview")
async def billing_overview(admin: Dict = Depends(get_admin_user)):
    """
    Vue d'ensemble revenus: users par plan, growth, tokens consommés.
    Note: Les montants monétaires réels nécessitent l'intégration Stripe.
    Cette route expose les métriques d'usage qui alimentent les calculs.
    """
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    try:
        # Users by plan with counts
        plan_res = db.table("v_plan_distribution").select("*").execute()
        plans = plan_res.data or []

        # New users this month vs last month
        now = datetime.now(timezone.utc)
        this_month = now.replace(day=1).isoformat()
        last_month_start = (now.replace(day=1) - timedelta(days=1)).replace(day=1).isoformat()

        this_month_users = (db.table("users").select("id", count="exact")
                            .gte("created_at", this_month).execute()).count or 0
        last_month_users = (db.table("users").select("id", count="exact")
                            .gte("created_at", last_month_start)
                            .lt("created_at", this_month).execute()).count or 0

        # Token consumption (proxy for revenue)
        tokens_res = db.table("users").select("plan, total_tokens_used").execute()
        tokens_by_plan: Dict[str, int] = {}
        for row in (tokens_res.data or []):
            p = row.get("plan", "free")
            tokens_by_plan[p] = tokens_by_plan.get(p, 0) + (row.get("total_tokens_used") or 0)

        # Pro and enterprise user counts
        pro_count = next((p["user_count"] for p in plans if p["plan"] == "pro"), 0)
        enterprise_count = next((p["user_count"] for p in plans if p["plan"] == "enterprise"), 0)

        return success_response({
            "plan_distribution": plans,
            "tokens_by_plan": tokens_by_plan,
            "growth": {
                "new_users_this_month": this_month_users,
                "new_users_last_month": last_month_users,
                "growth_pct": round((this_month_users - last_month_users) / max(last_month_users, 1) * 100, 2),
            },
            "paying_users": pro_count + enterprise_count,
            "note": "Intégrer Stripe pour les montants financiers réels (MRR, ARR, transactions)",
        })
    except Exception as e:
        logger.error("billing_overview error: %s", e)
        return error_response(str(e), 500)


@router.get("/billing/usage")
async def billing_usage(
    days: int = Query(30, ge=1, le=90),
    admin: Dict = Depends(get_admin_user),
):
    """Consommation globale par jour et par modèle (tokens et requêtes)."""
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    try:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        res = db.table("usage_logs").select("created_at, model_used, tokens_used, endpoint") \
            .gte("created_at", since).execute()
        data = res.data or []

        by_day: Dict[str, Any] = {}
        for row in data:
            day = row["created_at"][:10]
            if day not in by_day:
                by_day[day] = {"date": day, "total_requests": 0, "total_tokens": 0, "models": {}}
            by_day[day]["total_requests"] += 1
            by_day[day]["total_tokens"] += row.get("tokens_used") or 0
            mdl = row.get("model_used") or "unknown"
            by_day[day]["models"][mdl] = by_day[day]["models"].get(mdl, 0) + 1

        return success_response({
            "period_days": days,
            "daily": sorted(by_day.values(), key=lambda x: x["date"]),
            "total_requests": len(data),
            "total_tokens": sum(r.get("tokens_used") or 0 for r in data),
        })
    except Exception as e:
        logger.error("billing_usage error: %s", e)
        return error_response(str(e), 500)


# ─── SYSTEM ───────────────────────────────────────────────────────────────────

@router.get("/system/health")
async def system_health(admin: Dict = Depends(get_admin_user)):
    """
    Santé du système: base de données, requêtes récentes, erreurs.
    """
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    try:
        settings = get_settings()
        health_checks = {}

        # Supabase DB check
        try:
            test = db.table("users").select("id").limit(1).execute()
            health_checks["supabase"] = {"status": "healthy", "latency_ms": None}
        except Exception as e:
            health_checks["supabase"] = {"status": "down", "error": str(e)}

        # Recent error rate (last 5 min)
        from_ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        recent_res = db.table("usage_logs").select("status_code").gte("created_at", from_ts).execute()
        recent = recent_res.data or []
        total_recent = len(recent)
        errors_recent = sum(1 for r in recent if (r.get("status_code") or 200) >= 400)
        error_rate = round(errors_recent / max(total_recent, 1) * 100, 2)

        # Avg latency last hour
        hour_ts = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        lat_res = db.table("usage_logs").select("request_duration_ms").gte("created_at", hour_ts).execute()
        lat_data = [r["request_duration_ms"] for r in (lat_res.data or []) if r.get("request_duration_ms")]
        avg_latency = int(sum(lat_data) / len(lat_data)) if lat_data else 0

        # Moderation backlog
        mod_res = db.table("moderation_queue").select("id", count="exact").eq("status", "pending").execute()
        mod_pending = mod_res.count or 0

        return success_response({
            "services": [
                {"service": "Supabase (PostgreSQL)", **health_checks.get("supabase", {"status": "unknown"})},
                {"service": "Redis (Upstash)", "status": "healthy" if settings.upstash_redis_url else "not_configured"},
                {"service": "Cloudflare R2", "status": "healthy" if settings.r2_account_id else "not_configured"},
                {"service": "Firebase FCM", "status": "healthy" if settings.fcm_server_key else "not_configured"},
                {"service": "Groq LLM", "status": "healthy" if settings.groq_api_key else "not_configured"},
                {"service": "Gemini", "status": "healthy" if settings.gemini_api_key else "not_configured"},
                {"service": "ElevenLabs TTS", "status": "healthy" if settings.elevenlabs_api_key else "not_configured"},
                {"service": "Pinecone Vectors", "status": "healthy" if settings.pinecone_api_key else "not_configured"},
            ],
            "metrics": {
                "error_rate_5min_pct": error_rate,
                "avg_latency_1h_ms": avg_latency,
                "requests_last_5min": total_recent,
                "moderation_backlog": mod_pending,
            }
        })
    except Exception as e:
        logger.error("system_health error: %s", e)
        return error_response(str(e), 500)


@router.get("/system/logs")
async def system_logs(
    hours: int = Query(1, ge=1, le=24),
    endpoint: Optional[str] = Query(None),
    status_code_gte: Optional[int] = Query(None),
    admin: Dict = Depends(get_admin_user),
):
    """Logs d'accès récents avec filtres."""
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    try:
        from_ts = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        q = db.table("usage_logs").select(
            "id, user_id, endpoint, model_used, tokens_used, request_duration_ms, status_code, error_message, created_at"
        ).gte("created_at", from_ts).order("created_at", desc=True).limit(200)

        if endpoint:
            q = q.ilike("endpoint", f"%{endpoint}%")
        if status_code_gte:
            q = q.gte("status_code", status_code_gte)

        res = q.execute()
        return success_response({"logs": res.data or [], "hours": hours})
    except Exception as e:
        logger.error("system_logs error: %s", e)
        return error_response(str(e), 500)


# ─── AUDIT ────────────────────────────────────────────────────────────────────

@router.get("/audit/logs")
async def audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    action: Optional[str] = Query(None),
    admin_email: Optional[str] = Query(None),
    entity_type: Optional[str] = Query(None),
    admin: Dict = Depends(get_admin_user),
):
    """Journal complet des actions admin (immuable)."""
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)

    if admin["role"] not in ("super_admin", "admin", "auditor"):
        return error_response("Accès refusé", 403)

    try:
        q = db.table("admin_audit_log").select("*")
        if action:
            q = q.ilike("action", f"%{action}%")
        if admin_email:
            q = q.eq("admin_email", admin_email)
        if entity_type:
            q = q.eq("entity_type", entity_type)

        count_q = db.table("admin_audit_log").select("id", count="exact")
        total = (count_q.execute()).count or 0
        offset = (page - 1) * page_size
        q = q.order("created_at", desc=True).range(offset, offset + page_size - 1)
        res = q.execute()

        return success_response({
            "logs": res.data or [],
            "pagination": {
                "page": page, "page_size": page_size, "total": total,
                "total_pages": ceil(total / page_size) if total else 1,
            }
        })
    except Exception as e:
        logger.error("audit_logs error: %s", e)
        return error_response(str(e), 500)


# ─── ADMIN TEAM ───────────────────────────────────────────────────────────────

@router.get("/team")
async def get_team(admin: Dict = Depends(get_admin_user)):
    """Liste des membres de l'équipe admin."""
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    if admin["role"] not in ("super_admin", "admin"):
        return error_response("Accès refusé", 403)
    try:
        res = db.table("admin_users").select(
            "id, email, full_name, role, is_active, two_fa_enabled, last_login_at, created_at"
        ).order("created_at", desc=False).execute()
        return success_response({"team": res.data or []})
    except Exception as e:
        logger.error("get_team error: %s", e)
        return error_response(str(e), 500)


# ─── SETTINGS ─────────────────────────────────────────────────────────────────

@router.get("/settings")
async def get_settings_api(admin: Dict = Depends(get_admin_user)):
    """Configuration dynamique de la plateforme."""
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    try:
        res = db.table("admin_settings").select("*").execute()
        return success_response({"settings": res.data or []})
    except Exception as e:
        logger.error("get_settings error: %s", e)
        return error_response(str(e), 500)


@router.put("/settings/{key}")
async def update_setting(
    key: str,
    body: SettingUpdateRequest,
    request: Request,
    admin: Dict = Depends(get_admin_user),
):
    """Met à jour une clé de configuration."""
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    if admin["role"] not in ("super_admin", "admin"):
        return error_response("Accès refusé — super_admin requis", 403)
    try:
        import json
        db.table("admin_settings").upsert({
            "key": key,
            "value": body.value if isinstance(body.value, str) else json.dumps(body.value),
            "description": body.description,
            "updated_by": admin["id"],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        _audit(admin, "update_setting", "admin_settings", key, {"value": str(body.value)}, request)
        return success_response({"key": key, "updated": True})
    except Exception as e:
        logger.error("update_setting error: %s", e)
        return error_response(str(e), 500)


# ─── CONVERSATIONS ────────────────────────────────────────────────────────────

@router.get("/conversations")
async def list_conversations(
    user_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    admin: Dict = Depends(get_admin_user),
):
    """Liste des conversations avec filtres et pagination."""
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    try:
        q = db.table("chat_sessions").select(
            "id, user_id, title, model_used, total_messages, total_tokens, language, created_at, updated_at, users(email, full_name)"
        )
        if user_id:
            q = q.eq("user_id", user_id)

        total = (db.table("chat_sessions").select("id", count="exact").execute()).count or 0
        offset = (page - 1) * page_size
        q = q.order("created_at", desc=True).range(offset, offset + page_size - 1)
        res = q.execute()

        return success_response({
            "conversations": res.data or [],
            "pagination": {
                "page": page, "page_size": page_size, "total": total,
                "total_pages": ceil(total / page_size) if total else 1,
            }
        })
    except Exception as e:
        logger.error("list_conversations error: %s", e)
        return error_response(str(e), 500)


@router.get("/conversations/{session_id}/messages")
async def get_conversation_messages(
    session_id: str,
    admin: Dict = Depends(get_admin_user),
):
    """Messages complets d'une conversation."""
    db = _db()
    if not db:
        return error_response("Base indisponible", 503)
    try:
        session_res = db.table("chat_sessions").select("*, users(email, full_name)") \
            .eq("id", session_id).limit(1).execute()
        if not session_res.data:
            return error_response("Conversation introuvable", 404)

        msgs_res = db.table("messages").select("*") \
            .eq("session_id", session_id).order("created_at", desc=False).execute()

        return success_response({
            "session": session_res.data[0],
            "messages": msgs_res.data or [],
        })
    except Exception as e:
        logger.error("get_conversation_messages error: %s", e)
        return error_response(str(e), 500)
