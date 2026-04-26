"""Omni agent features: image orchestration, calls, and screen awareness."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from PIL import Image, ImageDraw, ImageFont

from core.config import get_settings
from core.database import get_supabase_admin
from services import image_gen_service, storage_service

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_prompt(prompt: str) -> str:
    return " ".join((prompt or "").strip().split())


def _optimized_prompt(user_prompt: str, style: str, quality_level: str) -> str:
    subject = _normalize_prompt(user_prompt) or "cinematic scene"
    style_map = {
        "realistic": "in the style of National Geographic photography",
        "cartoon": "high-quality stylized cartoon art",
        "artistic": "fine art composition with expressive brushwork",
        "3d": "premium 3D render with global illumination",
    }
    quality_map = {
        "simple": "clean high quality",
        "detailed": "photorealistic",
        "hyper": "ultra detailed hyperrealistic",
    }
    style_txt = style_map.get(style.lower(), style_map["realistic"])
    quality_txt = quality_map.get(quality_level.lower(), quality_map["detailed"])
    return (
        f"A {quality_txt} {subject}, detailed textures, strong subject separation, "
        f"balanced composition using rule of thirds, natural cinematic lighting, "
        f"shot on Canon EOS R5 85mm f/1.4, professional color grading, slight vignette, "
        f"{style_txt}."
    )


async def _moderate_prompt(prompt: str) -> dict:
    settings = get_settings()
    if not settings.openai_api_key:
        return {"passed": True, "flags": {}}
    try:
        async with httpx.AsyncClient(timeout=40.0) as client:
            r = await client.post(
                "https://api.openai.com/v1/moderations",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={"model": "omni-moderation-latest", "input": prompt},
            )
        if r.status_code >= 400:
            return {"passed": True, "flags": {"moderation_http_error": r.status_code}}
        data = r.json()
        result = (data.get("results") or [{}])[0]
        flagged = bool(result.get("flagged"))
        return {"passed": not flagged, "flags": result.get("categories", {})}
    except Exception as e:
        logger.warning("Moderation fallback pass: %s", e)
        return {"passed": True, "flags": {"moderation_fallback": True}}


async def _watermark_image(image_url: str, user_id: str) -> str:
    async with httpx.AsyncClient(timeout=90.0) as client:
        r = await client.get(image_url)
        r.raise_for_status()
        image = Image.open(io.BytesIO(r.content)).convert("RGBA")

    overlay = Image.new("RGBA", image.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    text = "ChadGPT"
    font = ImageFont.load_default()
    txt_w = int(draw.textlength(text, font=font))
    txt_h = 14
    x = max(10, image.width - txt_w - 20)
    y = max(10, image.height - txt_h - 16)
    draw.text((x, y), text, fill=(255, 255, 255, 80), font=font)

    out = Image.alpha_composite(image, overlay).convert("RGB")
    buf = io.BytesIO()
    out.save(buf, format="JPEG", quality=92, optimize=True)
    _, public_url = await storage_service.upload_bytes(
        buf.getvalue(),
        key_prefix=f"generated/watermarked/{user_id}",
        filename=f"wm_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.jpg",
        content_type="image/jpeg",
    )
    return public_url


def _extract_url_from_caption(caption: str) -> Optional[str]:
    m = re.search(r"\((https?://[^\)]+)\)", caption or "")
    return m.group(1) if m else None


async def create_generated_image(
    *,
    user_id: str,
    session_id: Optional[str],
    original_prompt: str,
    style: str,
    quality_level: str,
    parent_image_id: Optional[str] = None,
    edit_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    optimized = _optimized_prompt(original_prompt if not edit_prompt else edit_prompt, style, quality_level)
    moderation = await _moderate_prompt(optimized)
    if not moderation["passed"]:
        return {
            "blocked": True,
            "message": "Cette demande n'est pas autorisée par la politique de contenu.",
            "moderation_flags": moderation["flags"],
        }

    if edit_prompt and parent_image_id:
        final_prompt = (
            f"Change only what is requested: {edit_prompt}. Keep identity, composition, and all other details identical."
        )
    else:
        final_prompt = optimized

    caption, urls = await image_gen_service.generate_image_and_upload(final_prompt, user_id=user_id)
    raw_url = urls[0] if urls else _extract_url_from_caption(caption)
    if not raw_url:
        raise RuntimeError("Image générée mais URL indisponible")
    watermarked_url = await _watermark_image(raw_url, user_id=user_id)

    payload = {
        "user_id": user_id,
        "session_id": session_id,
        "original_prompt": original_prompt,
        "optimized_prompt": final_prompt,
        "revised_prompt": final_prompt,
        "image_url": raw_url,
        "watermarked_url": watermarked_url,
        "style": style,
        "quality_level": quality_level,
        "content_filter_passed": True,
        "moderation_flags": moderation["flags"],
        "generation_cost": 0.0,
        "parent_image_id": parent_image_id,
        "created_at": _utc_now_iso(),
    }
    db = get_supabase_admin()
    inserted = None
    if db:
        try:
            res = db.table("generated_images").insert(payload).execute()
            rows = getattr(res, "data", None) or []
            inserted = rows[0] if rows else None
            if edit_prompt and inserted and inserted.get("id"):
                db.table("image_edit_history").insert(
                    {
                        "image_id": inserted["id"],
                        "edit_prompt": edit_prompt,
                        "edited_url": watermarked_url,
                        "edit_type": "inpainting_prompt",
                        "created_at": _utc_now_iso(),
                    }
                ).execute()
        except Exception as e:
            logger.warning("generated_images insert failed: %s", e)

    return {
        "blocked": False,
        "record": inserted or payload,
    }


def _default_call_settings(user_id: str) -> dict:
    return {
        "user_id": user_id,
        "secretary_enabled": False,
        "active_hours": {"start": "09:00", "end": "18:00"},
        "voice_type": "female_fr",
        "custom_greeting": "",
        "whitelist_contacts": [],
        "blacklist_contacts": [],
        "forward_urgent_calls": True,
        "auto_sms_reply": False,
        "auto_sms_template": "Je suis actuellement occupé. Mon assistant IA prendra votre message.",
    }


async def save_call_settings(user_id: str, settings_payload: dict) -> dict:
    db = get_supabase_admin()
    # Accept both "enabled" and "secretary_enabled" from Flutter
    secretary_enabled = settings_payload.get(
        "secretary_enabled",
        settings_payload.get("enabled", False),
    )
    clean = {
        "user_id": user_id,
        "secretary_enabled": bool(secretary_enabled),
        "active_hours": settings_payload.get("active_hours") or {"start": "09:00", "end": "18:00"},
        "voice_type": settings_payload.get("voice_type") or "female_fr",
        "custom_greeting": settings_payload.get("custom_greeting") or "",
        "whitelist_contacts": settings_payload.get("whitelist_contacts") or [],
        "blacklist_contacts": settings_payload.get("blacklist_contacts") or [],
        "forward_urgent_calls": bool(settings_payload.get("forward_urgent_calls", True)),
        "auto_sms_reply": bool(settings_payload.get("auto_sms_reply", False)),
        "auto_sms_template": settings_payload.get("auto_sms_template")
            or "Je suis actuellement occupé. Mon assistant IA prendra votre message.",
        "updated_at": _utc_now_iso(),
    }
    if not db:
        return clean
    try:
        db.table("call_settings").upsert(clean, on_conflict="user_id").execute()
    except Exception as e:
        logger.warning("save_call_settings upsert failed: %s", e)
    return clean


async def get_call_settings(user_id: str) -> dict:
    db = get_supabase_admin()
    defaults = _default_call_settings(user_id)
    if not db:
        return defaults
    try:
        res = db.table("call_settings").select("*").eq("user_id", user_id).limit(1).execute()
        rows = getattr(res, "data", None) or []
        if rows:
            row = rows[0]
            # Normalise: accept legacy "enabled" column if "secretary_enabled" absent
            if "secretary_enabled" not in row and "enabled" in row:
                row["secretary_enabled"] = row.pop("enabled")
            return row
    except Exception as e:
        logger.warning("get_call_settings failed: %s", e)
    return defaults


def _simple_sentiment(text: str) -> str:
    t = (text or "").lower()
    if any(k in t for k in ["urgent", "vite", "immédiat", "asap"]):
        return "pressé"
    if any(k in t for k in ["colère", "fâché", "problème", "plainte"]):
        return "énervé"
    return "calme"


async def process_inbound_call(user_id: str, payload: dict) -> dict:
    caller_phone = payload.get("caller_phone") or "unknown"
    transcript = payload.get("transcription") or ""
    reason = payload.get("reason") or "raison non précisée"
    urgency = payload.get("urgency_level") or ("urgent" if "urgent" in transcript.lower() else "normal")
    summary = (
        f"📞 Appel reçu de {payload.get('caller_name') or caller_phone}\n"
        f"🎭 Sentiment : {_simple_sentiment(transcript)}\n"
        f"💬 Raison : {reason}\n"
        f"⚡ Urgence : {urgency}\n"
        f"📋 Message : {(transcript or 'Aucun message transcrit')[:900]}"
    )
    record = {
        "user_id": user_id,
        "caller_phone": caller_phone,
        "caller_name": payload.get("caller_name"),
        "call_timestamp": payload.get("call_timestamp") or _utc_now_iso(),
        "call_duration_seconds": int(payload.get("call_duration_seconds") or 0),
        "transcription": transcript,
        "summary": summary,
        "sentiment": _simple_sentiment(transcript),
        "urgency_level": urgency,
        "intentions": payload.get("intentions") or {},
        "recording_url": payload.get("recording_url"),
        "actions_taken": payload.get("actions_taken") or {},
        "user_read": False,
        "created_at": _utc_now_iso(),
    }
    db = get_supabase_admin()
    if db:
        try:
            db.table("inbound_calls").insert(record).execute()
        except Exception as e:
            logger.warning("inbound_calls insert failed: %s", e)
    return record


def frame_signature(frame_base64: str) -> str:
    return hashlib.sha256(frame_base64.encode("utf-8")).hexdigest()


def frame_similarity(sig_a: str, sig_b: str) -> float:
    if not sig_a or not sig_b:
        return 0.0
    common = sum(1 for a, b in zip(sig_a, sig_b) if a == b)
    return common / max(1, min(len(sig_a), len(sig_b)))


async def analyze_screen_frame(payload: dict) -> dict:
    frame_b64 = payload.get("frame_base64") or ""
    if not frame_b64:
        return {"result": "RIEN"}
    previous = payload.get("previous_signature") or ""
    sig = frame_signature(frame_b64)
    similarity = frame_similarity(sig, previous)
    threshold = float(get_settings().omni_screen_similarity_threshold)
    if previous and similarity >= threshold:
        return {"result": "RIEN", "signature": sig, "skipped": True}

    prompt = (payload.get("context_prompt") or "").strip()
    if "banque" in prompt.lower() and "http://" in prompt.lower():
        alert = {
            "type": "warning",
            "app_detected": "browser",
            "issue": "possible_phishing",
            "message": "La page semble sensible avec connexion non sécurisée.",
            "suggestion": "Vérifiez l'URL et utilisez uniquement des pages HTTPS officielles.",
        }
    else:
        alert = {"result": "RIEN"}
    alert["signature"] = sig
    return alert


async def create_screen_session(user_id: str, payload: dict) -> dict:
    row = {
        "user_id": user_id,
        "session_start": payload.get("session_start") or _utc_now_iso(),
        "session_end": payload.get("session_end"),
        "frames_analyzed": int(payload.get("frames_analyzed") or 0),
        "alerts_triggered": int(payload.get("alerts_triggered") or 0),
        "apps_detected": payload.get("apps_detected") or {},
        "created_at": _utc_now_iso(),
    }
    db = get_supabase_admin()
    if db:
        try:
            res = db.table("screen_sessions").insert(row).execute()
            rows = getattr(res, "data", None) or []
            if rows:
                return rows[0]
        except Exception as e:
            logger.warning("screen_sessions insert failed: %s", e)
    return row


async def create_screen_alert(user_id: str, payload: dict) -> dict:
    row = {
        "session_id": payload.get("session_id"),
        "alert_type": payload.get("alert_type") or "info",
        "app_context": payload.get("app_context"),
        "message": payload.get("message") or "Alerte IA",
        "suggestion": payload.get("suggestion"),
        "screenshot_url": payload.get("screenshot_url"),
        "user_action": payload.get("user_action"),
        "created_at": _utc_now_iso(),
    }
    db = get_supabase_admin()
    if db:
        try:
            res = db.table("screen_alerts").insert(row).execute()
            rows = getattr(res, "data", None) or []
            if rows:
                return rows[0]
        except Exception as e:
            logger.warning("screen_alerts insert failed: %s", e)
    return row
