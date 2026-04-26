"""Détection d'intentions « action appareil » sans service payant (ex. SMS via SIM)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

_PHONE_E164 = re.compile(r"\+\d{8,15}\b")
# +235 68 66 37 37, +235-686-63737, etc.
_PHONE_E164_SPACED = re.compile(r"\+[\d\s\-\u00a0·.]{10,30}")
_PHONE_00 = re.compile(r"\b00(\d{8,14})\b")
_DIGITS_RUN = re.compile(r"(?<!\d)(\d{8,12})(?!\d)")


@dataclass(frozen=True)
class SmsDraftIntent:
    """Numéro normalisé pour métadonnée device_action côté client."""

    to_e164: str


def _normalize_phone(raw: str) -> Optional[str]:
    s = raw.strip()
    if not s:
        return None
    digits = re.sub(r"\D", "", s)
    if s.startswith("00"):
        digits = digits[2:]
    if len(digits) < 8:
        return None
    # Numéros locaux Tchad (8 chiffres) -> +235XXXXXXXX
    if len(digits) == 8:
        return f"+235{digits}"
    if digits.startswith("0") and len(digits) == 9:
        return f"+235{digits[1:]}"
    if digits.startswith("235") and len(digits) >= 11:
        return f"+{digits}"
    return f"+{digits}"


def _extract_phone(text: str) -> Optional[str]:
    """Premier numéro plausible dans le message."""
    m = _PHONE_E164.search(text)
    if m:
        return _normalize_phone(m.group(0))

    m_sp = _PHONE_E164_SPACED.search(text.replace("\u00a0", " "))
    if m_sp:
        norm = _normalize_phone(m_sp.group(0))
        if norm:
            return norm

    m2 = _PHONE_00.search(text)
    if m2:
        return _normalize_phone("+" + m2.group(1))

    compact = re.sub(r"\s+", "", text)
    m3 = _DIGITS_RUN.search(compact)
    if m3:
        return _normalize_phone(m3.group(1))
    return None


def _has_sms_send_intent(text: str) -> bool:
    """Heuristique : l'utilisateur veut envoyer / rédiger un SMS, pas une question générale."""
    lower = text.lower()
    if re.search(r"\b(send|text)\s+(an?\s+)?(sms|text message)\b", lower):
        return True
    if re.search(r"\b(sms|texto)\b", lower):
        return True
    if re.search(r"\b(numéro|numero)\b", lower) and re.search(
        r"\b(envoy|envoyer|envoie|à\s+envoyer|a\s+envoyer)\b", lower
    ):
        return True
    if re.search(r"\b(envoyer|envoie|envoy)\b", lower) and (
        re.search(r"\b(sms|texto)\b", lower)
        or (re.search(r"\bmessage\b", lower) and _PHONE_E164.search(text) is not None)
    ):
        return True
    if re.search(r"\b(rédige|rédiger|redige|rediger|écris|ecris)\b", lower) and (
        re.search(r"\b(sms|texto|message)\b", lower) or _PHONE_E164.search(text) is not None
    ):
        return True
    return False


def parse_send_sms_intent(message: str) -> Optional[SmsDraftIntent]:
    """
    Détecte une demande d'envoi / rédaction de SMS vers un numéro.
    Ne déclenche pas d'envoi serveur : le client envoie via la carte SIM.
    """
    text = (message or "").strip()
    if len(text) < 8:
        return None
    if not _has_sms_send_intent(text):
        return None
    phone = _extract_phone(text)
    if not phone:
        return None
    return SmsDraftIntent(to_e164=phone)
