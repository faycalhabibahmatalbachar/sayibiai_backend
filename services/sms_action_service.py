"""Service métier SMS/Contacts (queue + alias + recherche)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.database import get_supabase_admin


def _db():
    return get_supabase_admin()


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def normalize_phone(phone: str) -> str:
    raw = (phone or "").strip()
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return ""
    if raw.startswith("+"):
        return f"+{digits}"
    if raw.startswith("00"):
        return f"+{digits[2:]}" if len(digits) > 2 else ""
    # Défaut Tchad: 8 chiffres locaux -> +235XXXXXXXX
    if len(digits) == 8:
        return f"+235{digits}"
    # Formats locaux avec 0 initial (ex: 06xxxxxx)
    if digits.startswith("0") and len(digits) == 9:
        return f"+235{digits[1:]}"
    # Si l'utilisateur a déjà écrit 235 sans '+'
    if digits.startswith("235") and len(digits) >= 11:
        return f"+{digits}"
    return f"+{digits}"


def mask_phone(phone: str) -> str:
    p = normalize_phone(phone)
    if len(p) < 7:
        return "•••"
    return f"{p[:4]} ••• •• {p[-2:]}"


async def sync_contacts(user_id: str, contacts: List[Dict[str, Any]]) -> Dict[str, int]:
    c = _db()
    if not c:
        return {"upserted": 0}
    count = 0
    for contact in contacts:
        source_id = str(contact.get("contact_id") or contact.get("id") or "").strip()
        if not source_id:
            continue
        display_name = str(contact.get("display_name") or "").strip()
        phones = contact.get("phone_numbers") if isinstance(contact.get("phone_numbers"), list) else []
        normalized_phones = []
        for ph in phones:
            if not isinstance(ph, dict):
                continue
            num = normalize_phone(str(ph.get("number") or ""))
            if not num:
                continue
            normalized_phones.append(
                {
                    "number": num,
                    "label": str(ph.get("label") or "mobile"),
                    "is_primary": bool(ph.get("is_primary", False)),
                }
            )
        payload = {
            "user_id": user_id,
            "source_contact_id": source_id,
            "display_name": display_name,
            "normalized_name": normalize_name(display_name),
            "phones": normalized_phones,
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            c.table("contact_identities").upsert(payload, on_conflict="user_id,source_contact_id").execute()
            count += 1
        except Exception:
            continue
    return {"upserted": count}


async def search_contacts(user_id: str, query: str, limit: int = 10) -> List[Dict[str, Any]]:
    c = _db()
    if not c:
        return []
    q = normalize_name(query)
    if not q:
        return []
    rows = (
        c.table("contact_identities")
        .select("*")
        .eq("user_id", user_id)
        .order("last_seen_at", desc=True)
        .limit(200)
        .execute()
    ).data or []
    out: List[Dict[str, Any]] = []
    for row in rows:
        name = normalize_name(str(row.get("display_name") or ""))
        if q not in name and not all(part in name for part in q.split(" ")):
            continue
        phones = row.get("phones") if isinstance(row.get("phones"), list) else []
        phone_preview = ""
        if phones and isinstance(phones[0], dict):
            phone_preview = mask_phone(str(phones[0].get("number") or ""))
        out.append(
            {
                "id": row.get("id"),
                "contact_id": row.get("source_contact_id"),
                "display_name": row.get("display_name"),
                "phone_numbers": phones,
                "phone_preview": phone_preview,
            }
        )
        if len(out) >= limit:
            break
    return out


async def create_sms_draft(
    user_id: str,
    *,
    to_e164: str,
    body: str,
    contact_identity_id: Optional[str] = None,
    request_id: Optional[str] = None,
    client_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    c = _db()
    if not c:
        raise RuntimeError("Base indisponible")
    to = normalize_phone(to_e164)
    if not to:
        raise ValueError("Numéro invalide")
    msg = (body or "").strip()
    if not msg:
        raise ValueError("Message vide")
    if request_id:
        existing = (
            c.table("sms_action_queue")
            .select("*")
            .eq("user_id", user_id)
            .eq("request_id", request_id)
            .limit(1)
            .execute()
        ).data or []
        if existing:
            return existing[0]
    row = {
        "user_id": user_id,
        "contact_identity_id": contact_identity_id,
        "to_e164": to,
        "body": msg,
        "status": "draft",
        "origin": "agent",
        "provider": "device",
        "request_id": request_id,
        "client_meta": client_meta or {},
    }
    res = c.table("sms_action_queue").insert(row).execute()
    data = res.data or []
    return data[0] if data else row


async def update_sms_status(
    user_id: str,
    sms_id: str,
    status: str,
    *,
    error_message: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    c = _db()
    if not c:
        return None
    patch: Dict[str, Any] = {"status": status}
    if status == "sent":
        patch["sent_at"] = datetime.now(timezone.utc).isoformat()
    if error_message:
        patch["error_message"] = error_message[:500]
    res = c.table("sms_action_queue").update(patch).eq("id", sms_id).eq("user_id", user_id).execute()
    rows = res.data or []
    if rows:
        return rows[0]
    fallback = (
        c.table("sms_action_queue")
        .select("*")
        .eq("id", sms_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    ).data or []
    return fallback[0] if fallback else None


async def list_sms_actions(user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    c = _db()
    if not c:
        return []
    return (
        c.table("sms_action_queue")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    ).data or []

