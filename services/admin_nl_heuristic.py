"""
Heuristiques recherche NL + réponses assistant admin (phase 1, sans LLM).
Les requêtes peuvent être journalisées dans admin_nl_search_log.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def parse_nl_user_query(query: str) -> Dict[str, Any]:
    """
    Traduit une phrase admin en filtres API (clés alignées sur GET /admin/users).
    Retourne uniquement les clés pertinentes (pas de 'all').
    """
    raw = (query or "").strip()
    if not raw:
        return {}

    s = _norm(raw)
    out: Dict[str, Any] = {}

    if re.search(
        r"churn|inactif|inactive|sans activite|pas utilise|non utilise|2 semaines|deux semaines|14 jours|abandon",
        s,
    ):
        out["status"] = "inactive"
    if re.search(r"banni|bannis|suspendu", s):
        out["status"] = "banned"
    if re.search(r"\bactif\b|active\b", s) and "inactif" not in s and "inactive" not in s:
        out["status"] = "active"

    if re.search(r"enterprise|vip|premium", s):
        out["plan"] = "enterprise"
    elif re.search(r"\bpro\b", s):
        out["plan"] = "pro"
    elif re.search(r"gratuit|free", s):
        out["plan"] = "free"

    if re.search(r"france|\bfr\b", s):
        out["country_code"] = "FR"
    if re.search(r"\bus\b|usa|etats-unis|united states", s):
        out["country_code"] = "US"
    if re.search(r"allemagne|germany|\bde\b", s):
        out["country_code"] = "DE"

    m = re.search(r"plus de\s*(\d+)\s*conversations?", s)
    if m:
        out["tags"] = "high-volume"
        out["_nl_note"] = f"Filtre conversation ≥ {m.group(1)} — affiner via API (total_sessions)."

    if re.search(r"100\s*conversations?|cent conversations?", s):
        out["tags"] = "high-volume"

    if re.search(r"email|e-mail", s) and "@" in raw:
        em = re.search(r"[\w.+-]+@[\w.-]+\.\w+", raw)
        if em:
            out["search"] = em.group(0)

    return out


def effective_user_list_params(
    parsed: Dict[str, Any],
    *,
    search: Optional[str] = None,
    plan: Optional[str] = None,
    status: Optional[str] = None,
    country_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    tags: Optional[str] = None,
) -> Dict[str, Any]:
    """Fusionne filtres existants + champs déduits du NL (valeurs NL en priorité)."""
    eff_search = parsed.get("search") or search
    eff_plan = parsed.get("plan") or plan
    eff_status = parsed.get("status") or status
    eff_cc = parsed.get("country_code") or country_code
    eff_tags = parsed.get("tags") or tags

    def norm_plan(p: Optional[str]) -> Optional[str]:
        if not p or str(p).lower() in ("all", ""):
            return None
        return str(p)

    def norm_status(st: Optional[str]) -> Optional[str]:
        if not st or str(st).lower() in ("all", ""):
            return None
        return str(st)

    cc = None
    if eff_cc:
        cc = str(eff_cc).strip().upper()[:2] or None

    return {
        "search": eff_search.strip() if eff_search else None,
        "plan": norm_plan(eff_plan),
        "status": norm_status(eff_status),
        "country_code": cc,
        "date_from": date_from,
        "date_to": date_to,
        "tags": eff_tags,
    }


def assistant_reply(
    message: str,
    *,
    kpis: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Réponse guidée sans inventer de données : cite les sources (KPI / routes).
    """
    m = (message or "").strip()
    low = _norm(m)
    bullets: List[str] = []
    sources: List[str] = []

    if re.search(r"combien.*utilisateur|total.*user|dau|actif", low):
        if kpis:
            bullets.append(
                f"Indicateurs dashboard (fn_dashboard_kpis) : "
                f"total_users ≈ {kpis.get('total_users', '—')}, "
                f"actifs mois ≈ {kpis.get('active_users_month', '—')}."
            )
        else:
            bullets.append(
                "Pour des chiffres à jour : GET /api/v1/admin/dashboard/kpis (ou RPC fn_dashboard_kpis)."
            )
        sources.append("GET /admin/dashboard/kpis")

    if re.search(r"suspendre|bannir|moderation", low):
        bullets.append(
            "Suspendre : POST /admin/users/{id}/ban avec raison (audit admin_audit_log). "
            "Zone Danger dans la fiche utilisateur côté UI."
        )
        sources.append("POST /admin/users/{id}/ban")

    if re.search(r"export|csv|json|vip", low):
        bullets.append(
            "Export : GET /admin/users-export/stream?format=csv|json. "
            "Segment VIP : filtre plan=enterprise ou tags dans GET /admin/users."
        )
        sources.append("GET /admin/users-export/stream")

    if re.search(r"recherche|langage|naturel|nl", low):
        bullets.append(
            "Recherche NL : POST /admin/users/nl-search (heuristique + comptage ; journal admin_nl_search_log)."
        )
        sources.append("POST /admin/users/nl-search")

    if re.search(r"rgpd|donnee|retention|anonym", low):
        bullets.append(
            "Politique : clé admin_settings.data_retention_policy ; suivi user_gdpr_retention (migration 011)."
        )
        sources.append("admin_settings.data_retention_policy")

    if not bullets:
        bullets.append(
            "Je peux orienter vers les routes admin documentées. "
            "Précisez : métriques, export, modération, RGPD ou recherche utilisateurs."
        )

    return {"reply": "\n".join(f"• {b}" for b in bullets), "sources": sources, "model": "heuristic_admin_v1"}
