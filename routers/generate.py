"""Génération de fichiers — CV, lettres, rapports, Excel, depuis le chat."""

import json
import uuid
from typing import Any, List

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse

from core.deps import get_current_user_id
from core.database import get_supabase_admin
from core.responses import error_response, success_response
from models.generate import (
    GenerateCVRequest,
    GenerateExcelRequest,
    GenerateFromChatRequest,
    GenerateLetterRequest,
    GenerateReportRequest,
)
from services import ai_router, file_generator
from services import storage_service
from services.usage_service import log_usage

router = APIRouter(prefix="/generate", tags=["generate"])


def _store_generated_file(
    user_id: str,
    file_type: str,
    filename: str,
    storage_path: str,
    prompt_used: str = "",
    session_id: str | None = None,
) -> str | None:
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
                "storage_path": storage_path,
                "prompt_used": (prompt_used or "")[:2000] or None,
                "session_id": session_id,
            }
        ).execute()
        return gid
    except Exception:
        return None


def _build_download_meta(file_id: str, storage_path: str) -> dict:
    signed = storage_service.get_presigned_url(storage_path, expires_in=60 * 60 * 24)
    meta = {
        "file_id": file_id,
        "download_url": f"/api/v1/generate/download/{file_id}",
    }
    if signed:
        meta["download_url_signed"] = signed
    return meta


async def _llm_json(prompt: str):
    """Demande une sortie structurée au LLM ; retourne (texte, tokens)."""
    out, _model, tok, _extra = await ai_router.run_chat(
        prompt + "\nRéponds uniquement avec le contenu demandé, sans préambule.",
        [],
        "auto",
        "auto",
        None,
        False,
        False,
    )
    return out, tok


@router.post("/cv")
async def generate_cv(body: GenerateCVRequest, user_id: str = Depends(get_current_user_id)):
    """Génère un CV Word à partir des champs structurés."""
    p = body.personal_info.model_dump()
    exp = [e.model_dump() for e in body.experience]
    edu = [e.model_dump() for e in body.education]
    data = file_generator.build_cv_docx(
        p,
        exp,
        edu,
        body.skills,
        body.language,
    )
    fname = f"CV_{p.get('full_name', 'sayibi').replace(' ', '_')}.docx"
    meta = await file_generator.upload_generated(data, "cv", fname, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    fid = _store_generated_file(
        user_id=user_id,
        file_type="cv",
        filename=meta["filename"],
        storage_path=meta["object_key"],
        prompt_used=json.dumps(p),
    )
    if fid:
        meta.update(_build_download_meta(fid, meta["object_key"]))
    await log_usage(user_id, "/generate/cv", None, "generate")
    return success_response(meta, "CV généré")


@router.post("/letter")
async def generate_letter(body: GenerateLetterRequest, user_id: str = Depends(get_current_user_id)):
    """Lettre de motivation ou administrative."""
    prompt = (
        f"Rédige une lettre de type « {body.type} » pour : {body.context}. "
        f"Destinataire : {body.recipient or 'non précisé'}. Ton : {body.tone}. Langue : {body.language}."
    )
    text, tok = await _llm_json(prompt)
    title = f"Lettre_{body.type}.docx"
    data = file_generator.build_letter_docx(text, title=body.type)
    meta = await file_generator.upload_generated(
        data,
        "letters",
        title,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    fid = _store_generated_file(
        user_id=user_id,
        file_type="letter",
        filename=meta["filename"],
        storage_path=meta["object_key"],
        prompt_used=prompt,
    )
    if fid:
        meta.update(_build_download_meta(fid, meta["object_key"]))
    await log_usage(user_id, "/generate/letter", tok, "llm")
    return success_response(meta, "Lettre générée")


@router.post("/report")
async def generate_report(body: GenerateReportRequest, user_id: str = Depends(get_current_user_id)):
    """Rapport PDF structuré."""
    prompt = (
        f"Rédige un rapport sur : {body.topic}. Sections : {', '.join(body.sections)}. "
        f"Données contextuelles : {body.data}. Langue : {body.language}."
    )
    body_text, tok = await _llm_json(prompt)
    pdf = file_generator.build_report_pdf(body.topic, body.sections, body_text)
    fname = f"rapport_{uuid.uuid4().hex[:8]}.pdf"
    meta = await file_generator.upload_generated(pdf, "reports", fname, "application/pdf")
    fid = _store_generated_file(
        user_id=user_id,
        file_type="report",
        filename=meta["filename"],
        storage_path=meta["object_key"],
        prompt_used=prompt,
    )
    if fid:
        meta.update(_build_download_meta(fid, meta["object_key"]))
    await log_usage(user_id, "/generate/report", tok, "llm")
    return success_response(meta, "Rapport généré")


@router.post("/excel")
async def generate_excel(body: GenerateExcelRequest, user_id: str = Depends(get_current_user_id)):
    """Tableur XLSX : le LLM propose des lignes synthétiques."""
    prompt = (
        f"Pour un fichier Excel intitulé « {body.title} », colonnes : {body.columns}. "
        f"Description des données : {body.data_description}. Langue : {body.language}. "
        "Réponds avec un JSON strict : {\"rows\": [[cell1, cell2, ...], ...]} uniquement."
    )
    raw, tok = await _llm_json(prompt)
    rows: List[List[Any]] = []
    try:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            obj = json.loads(raw[start : end + 1])
            rows = obj.get("rows") or []
    except Exception:
        rows = []
    if not rows:
        rows = [["—", "—"] for _ in range(3)]
    xlsx = file_generator.build_excel_workbook(body.title, body.columns, rows)
    fname = f"{body.title.replace(' ', '_')}.xlsx"
    meta = await file_generator.upload_generated(
        xlsx,
        "excel",
        fname,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    fid = _store_generated_file(
        user_id=user_id,
        file_type="excel",
        filename=meta["filename"],
        storage_path=meta["object_key"],
        prompt_used=prompt,
    )
    if fid:
        meta.update(_build_download_meta(fid, meta["object_key"]))
    await log_usage(user_id, "/generate/excel", tok, "llm")
    return success_response(meta, "Excel généré")


@router.post("/from_chat")
async def generate_from_chat(body: GenerateFromChatRequest, user_id: str = Depends(get_current_user_id)):
    """Transforme une conversation en document (export)."""
    c = get_supabase_admin()
    lines: List[str] = []
    if c:
        try:
            res = (
                c.table("messages")
                .select("role,content")
                .eq("session_id", body.session_id)
                .order("created_at", desc=False)
                .execute()
            )
            for m in res.data or []:
                lines.append(f"{m['role']}: {m['content']}")
        except Exception:
            pass
    blob = "\n".join(lines) or "(conversation vide)"
    prompt = (
        f"Transforme la conversation suivante en document de type {body.output_type} :\n\n{blob[:15000]}"
    )
    text, tok = await _llm_json(prompt)
    if body.output_type == "report":
        pdf = file_generator.build_report_pdf("Export conversation", ["Contenu"], text)
        meta = await file_generator.upload_generated(
            pdf,
            "exports",
            f"chat_export_{uuid.uuid4().hex[:8]}.pdf",
            "application/pdf",
        )
        file_type = "report"
    else:
        docx = file_generator.build_letter_docx(text, title="Export conversation")
        meta = await file_generator.upload_generated(
            docx,
            "exports",
            f"chat_export_{uuid.uuid4().hex[:8]}.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        file_type = "letter"
    fid = _store_generated_file(
        user_id=user_id,
        file_type=file_type,
        filename=meta["filename"],
        storage_path=meta["object_key"],
        prompt_used=prompt,
        session_id=body.session_id,
    )
    if fid:
        meta.update(_build_download_meta(fid, meta["object_key"]))
    await log_usage(user_id, "/generate/from_chat", tok, "llm")
    return success_response(meta, "Document créé depuis le chat")


@router.get("/download/{file_id}")
async def download_generated_file(file_id: str, user_id: str = Depends(get_current_user_id)):
    """Téléchargement sécurisé d'un fichier généré appartenant à l'utilisateur."""
    c = get_supabase_admin()
    if not c:
        return error_response("Base indisponible", 503)
    try:
        res = (
            c.table("generated_files")
            .select("id,user_id,filename,storage_path")
            .eq("id", file_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return error_response("Fichier introuvable", 404)
        row = rows[0]
        storage_path = row.get("storage_path")
        if not storage_path:
            return error_response("Chemin de stockage manquant", 500)
        signed = storage_service.get_presigned_url(storage_path, expires_in=60 * 60 * 24)
        if signed:
            return RedirectResponse(url=signed, status_code=307)
        return error_response("Téléchargement indisponible", 503)
    except Exception as e:
        return error_response(str(e), 500)
