"""Heuristiques « intelligence utilisateur » (scores, prédictions) — sans modèle ML externe."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def mask_email(email: Optional[str]) -> Optional[str]:
    if not email or "@" not in email:
        return email
    local, domain = email.split("@", 1)
    if len(local) <= 1:
        return f"*@{domain}"
    if len(local) <= 3:
        return f"{local[0]}*@{domain}"
    return f"{local[0]}…{local[-1]}@{domain}"


def mask_phone(phone: Optional[str]) -> Optional[str]:
    if not phone or len(phone) < 4:
        return None
    return f"…{phone[-4:]}"


def compute_ml_profile(user: Dict[str, Any]) -> Dict[str, Any]:
    """
    Scores 0–100 dérivés des champs v_admin_users_full (+ heuristiques simples).
    Remplaceable par un vrai pipeline ML (batch) alimentant user_ml_profiles.
    """
    tokens = int(user.get("total_tokens_used") or 0)
    sessions = int(user.get("total_sessions") or 0)
    msgs = int(user.get("total_messages") or 0)
    req_today = int(user.get("requests_today") or 0)
    risk = int(user.get("risk_score") or 0)
    plan = (user.get("plan") or "free").lower()
    status = (user.get("status") or "inactive").lower()

    # Engagement: volume + récence proxy (requests today)
    eng_raw = min(100, (sessions * 2 + msgs // 10 + req_today * 5 + min(tokens // 5000, 30)))
    engagement_score = max(0, min(100, eng_raw))

    # Churn risk: inverse de l’engagement + risque modération
    churn_risk = max(0, min(100, 100 - engagement_score + risk // 2))
    if status == "banned":
        churn_risk = 100
    if status == "inactive":
        churn_risk = min(100, churn_risk + 25)

    upsell_propensity = 0
    if plan == "free":
        upsell_propensity = max(0, min(100, engagement_score - 20 + (10 if tokens > 50_000 else 0)))
    elif plan == "pro":
        upsell_propensity = max(0, min(100, engagement_score // 2))  # upgrade enterprise

    # LTV en cents (estimation grossière : tokens * plan factor)
    plan_mult = {"free": 0.5, "pro": 12.0, "enterprise": 40.0}.get(plan, 1.0)
    ltv_estimate_cents = int(min(tokens * plan_mult * 0.01, 999_999_00))

    if churn_risk >= 66:
        health = "at_risk"
    elif churn_risk >= 40:
        health = "average"
    else:
        health = "healthy"

    return {
        "engagement_score": engagement_score,
        "churn_risk": churn_risk,
        "upsell_propensity": upsell_propensity if plan != "enterprise" else None,
        "ltv_estimate_cents": ltv_estimate_cents,
        "ltv_estimate_usd": round(ltv_estimate_cents / 100, 2),
        "health_label": health,
        "model_version": "heuristic_v1",
        "calculated_at": datetime.now(timezone.utc).isoformat(),
    }


def apply_list_mask(users: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for u in users:
        row = dict(u)
        if "email" in row:
            row["email_masked"] = mask_email(row.get("email"))
            row["email"] = mask_email(row.get("email"))
        out.append(row)
    return out


def sign_webhook_payload(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def dispatch_user_webhooks_sync(
    hooks: List[Dict[str, Any]],
    event: str,
    payload: Dict[str, Any],
) -> None:
    """POST best-effort vers les URLs configurées (tâche background)."""
    import httpx

    body_bytes = json.dumps({"event": event, "payload": payload}, default=str).encode("utf-8")
    base_headers = {"Content-Type": "application/json"}
    with httpx.Client(timeout=10.0) as client:
        for h in hooks:
            evts = h.get("events") or []
            if evts and event not in evts:
                continue
            url = h.get("url")
            if not url:
                continue
            hdrs = dict(base_headers)
            sec = h.get("secret")
            if sec:
                hdrs["X-ChadGPT-Signature"] = sign_webhook_payload(sec, body_bytes)
            try:
                client.post(url, content=body_bytes, headers=hdrs)
            except Exception as ex:
                logger.warning("webhook %s failed: %s", h.get("id"), ex)


def load_active_webhooks(db: Any) -> List[Dict[str, Any]]:
    try:
        res = db.table("admin_webhooks").select("id, url, secret, events").eq("is_active", True).execute()
        return res.data or []
    except Exception as e:
        logger.warning("webhooks list failed: %s", e)
        return []
