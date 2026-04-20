"""Création réelle de documents depuis le chat (mode +)."""

import json
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from core.database import get_supabase_admin
from core.config import get_settings
from services import file_generator, groq_service, mistral_service, storage_service


def _extract_json_object(raw: str) -> Optional[dict]:
    raw = raw.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None


def _build_download_meta(file_id: str, object_key: str) -> Dict[str, Any]:
    signed = storage_service.get_presigned_url(object_key, expires_in=60 * 60 * 24)
    out: Dict[str, Any] = {
        "file_id": file_id,
        "download_url": f"/api/v1/generate/download/{file_id}",
    }
    if signed:
        out["download_url_signed"] = signed
    return out


async def _llm(system: str, user: str) -> Tuple[str, Optional[int], str]:
    """Retourne (texte, tokens, modèle)."""
    settings = get_settings()
    if settings.groq_api_key:
        comp = await groq_service.chat_completion(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        text, tok = groq_service.extract_text_and_usage(comp)
        return text, tok, groq_service.DEFAULT_MODEL
    if settings.mistral_api_key:
        comp = await mistral_service.chat_completion(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        text, tok = mistral_service.extract_text_and_usage(comp)
        return text, tok, mistral_service.DEFAULT_MODEL
    raise RuntimeError("Aucune clé LLM pour la création de documents (GROQ ou MISTRAL).")


async def create_from_chat(
    user_message: str,
    create_type: str,
    user_id: str,
) -> Tuple[str, str, Optional[int], Dict[str, Any]]:
    """
    Retourne (réponse_markdown, model_label, tokens, metadata avec generated_file).
    """
    ct = (create_type or "cv").lower()
    meta: Dict[str, Any] = {}

    def _store_generated(file_type: str, filename: str, object_key: str) -> Optional[str]:
        c = get_supabase_admin()
        if not c:
            return None
        try:
            gid = str(uuid.uuid4())
            c.table("generated_files").insert(
                {
                    "id": gid,
                    "user_id": user_id,
                    "file_type": file_type,
                    "filename": filename,
                    "storage_path": object_key,
                    "prompt_used": user_message[:2000],
                }
            ).execute()
            return gid
        except Exception:
            return None

    if ct == "cv":
        system = (
            "Tu extrais des données pour un CV. Réponds avec UN SEUL objet JSON, sans markdown, "
            "clés: personal {full_name,email,phone,location,summary}, "
            "experience [{title,company,start,end,description}], "
            "education [{degree,school,year}], skills [str]. Texte en français si la demande est en français."
        )
        raw, tok, model = await _llm(system, f"Demande utilisateur :\n{user_message}")
        data = _extract_json_object(raw) or {}
        personal = data.get("personal") or {}
        experience = data.get("experience") or []
        education = data.get("education") or []
        skills = data.get("skills") or []
        if not personal.get("full_name"):
            personal["full_name"] = "Candidat"
        docx = file_generator.build_cv_docx(
            personal,
            experience if isinstance(experience, list) else [],
            education if isinstance(education, list) else [],
            skills if isinstance(skills, list) else [],
            "fr",
        )
        fname = f"CV_{personal.get('full_name', 'sayibi').replace(' ', '_')}.docx"
        up = await file_generator.upload_generated(
            docx,
            "cv",
            fname,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        meta["generated_file"] = {
            "type": "cv",
            "filename": fname,
            "url": up["url"],
        }
        fid = _store_generated("cv", fname, up["object_key"])
        if fid:
            meta["generated_file"].update(_build_download_meta(fid, up["object_key"]))
        text = (
            f"**CV généré** — téléchargement : [{fname}]({up['url']})\n\n"
            "Vous pouvez ouvrir le fichier Word et ajuster la mise en forme."
        )
        return text, f"Sayibi Création ({model})", tok, meta

    if ct == "letter":
        system = "Tu rédiges une lettre professionnelle complète selon la demande. Réponds avec le texte de la lettre uniquement, sans titre « Lettre » en en-tête markdown."
        body, tok, model = await _llm(system, user_message)
        fname = f"Lettre_{uuid.uuid4().hex[:8]}.docx"
        docx = file_generator.build_letter_docx(body, title="Lettre")
        up = await file_generator.upload_generated(
            docx,
            "letters",
            fname,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        meta["generated_file"] = {"type": "letter", "filename": fname, "url": up["url"]}
        fid = _store_generated("letter", fname, up["object_key"])
        if fid:
            meta["generated_file"].update(_build_download_meta(fid, up["object_key"]))
        text = f"**Lettre générée** — [{fname}]({up['url']})"
        return text, f"Sayibi Création ({model})", tok, meta

    if ct == "report":
        system = (
            "Produit un rapport structuré en français (plusieurs paragraphes) sur le sujet demandé. "
            "Pas de JSON, texte continu avec sous-titres en ## markdown."
        )
        body, tok, model = await _llm(system, user_message)
        title_match = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else "Rapport"
        sections = re.findall(r"^##\s+(.+)$", body, re.MULTILINE)
        if not sections:
            sections = ["Introduction", "Analyse", "Conclusion"]
        pdf = file_generator.build_report_pdf(title[:120], sections[:12], body)
        fname = f"rapport_{uuid.uuid4().hex[:8]}.pdf"
        up = await file_generator.upload_generated(pdf, "reports", fname, "application/pdf")
        meta["generated_file"] = {"type": "report", "filename": fname, "url": up["url"]}
        fid = _store_generated("report", fname, up["object_key"])
        if fid:
            meta["generated_file"].update(_build_download_meta(fid, up["object_key"]))
        text = f"**Rapport PDF généré** — [{fname}]({up['url']})\n\n{body[:800]}{'…' if len(body) > 800 else ''}"
        return text, f"Sayibi Création ({model})", tok, meta

    if ct == "excel":
        system = (
            "Pour un tableur, réponds UNIQUEMENT avec un JSON : "
            '{"title":"nom de la feuille","columns":["Col1","Col2"],"rows":[["a","b"],["c","d"]]} '
            "Colonnes et lignes cohérentes avec la demande. Pas de markdown."
        )
        raw, tok, model = await _llm(system, user_message)
        obj = _extract_json_object(raw) or {}
        title = str(obj.get("title") or "Données")
        columns = obj.get("columns") or ["A", "B"]
        rows = obj.get("rows") or []
        if not isinstance(columns, list):
            columns = ["Colonne 1", "Colonne 2"]
        if not rows:
            rows = [["—", "—"]]
        xlsx = file_generator.build_excel_workbook(title, [str(c) for c in columns], rows)
        fname = f"{title.replace(' ', '_')[:40]}.xlsx"
        up = await file_generator.upload_generated(
            xlsx,
            "excel",
            fname,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        meta["generated_file"] = {"type": "excel", "filename": fname, "url": up["url"]}
        fid = _store_generated("excel", fname, up["object_key"])
        if fid:
            meta["generated_file"].update(_build_download_meta(fid, up["object_key"]))
        text = (
            f"**Classeur Excel généré** — [{fname}]({up['url']})\n\n"
            f"Colonnes : {', '.join(map(str, columns))} — {len(rows)} ligne(s)."
        )
        return text, f"Sayibi Création ({model})", tok, meta

    raise ValueError(f"Type de création inconnu : {ct}")
