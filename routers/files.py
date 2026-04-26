"""Router Fichiers — indexation sémantique et recherche de fichiers."""

import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, UploadFile, File as FastAPIFile
from pydantic import BaseModel, Field

from core.database import get_supabase_admin
from core.deps import get_current_user_id
from core.responses import error_response, success_response
from services import storage_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/files", tags=["files"])


class FileScanManifest(BaseModel):
    """Manifeste de fichiers envoyé depuis Flutter (métadonnées uniquement, pas le contenu)."""
    files: List[dict] = Field(..., description="Liste de {name, path, size, type, modified}")


class FileSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    file_types: Optional[List[str]] = None
    limit: int = Field(default=10, ge=1, le=50)


async def _embed_text(text: str) -> Optional[List[float]]:
    """Génère un embedding vectoriel pour la recherche sémantique."""
    try:
        from core.config import get_settings
        import httpx
        s = get_settings()
        if not s.openai_api_key:
            return None
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {s.openai_api_key}"},
                json={"model": "text-embedding-3-small", "input": text[:8000]},
            )
            if r.status_code < 400:
                return r.json()["data"][0]["embedding"]
    except Exception as e:
        logger.debug("Embedding error: %s", e)
    return None


@router.post("/scan")
async def scan_files(
    body: FileScanManifest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Reçoit un manifeste de fichiers depuis Flutter et les indexe en base.
    Les métadonnées sont indexées avec embeddings pour la recherche sémantique.
    """
    try:
        c = get_supabase_admin()
        if not c:
            return error_response("Base de données non disponible", 503)

        indexed = 0
        for file_meta in body.files[:500]:  # Limiter à 500 fichiers
            name = file_meta.get("name", "")
            if not name:
                continue

            # Générer embedding basé sur le nom et type
            embed_text = f"{name} {file_meta.get('type', '')} {file_meta.get('path', '')}"
            embedding = await _embed_text(embed_text)

            row = {
                "user_id": user_id,
                "file_name": name,
                "file_path": file_meta.get("path", ""),
                "file_type": file_meta.get("type", ""),
                "file_size": file_meta.get("size", 0),
                "mime_type": file_meta.get("mime_type", ""),
                "metadata": {
                    "modified": file_meta.get("modified"),
                    "extension": name.rsplit(".", 1)[-1].lower() if "." in name else "",
                },
                "last_modified": file_meta.get("modified"),
            }

            try:
                # Upsert basé sur path + user_id
                existing = (
                    c.table("file_index")
                    .select("id")
                    .eq("user_id", user_id)
                    .eq("file_path", file_meta.get("path", ""))
                    .execute()
                )
                if existing.data:
                    c.table("file_index").update(row).eq(
                        "id", existing.data[0]["id"]
                    ).execute()
                else:
                    row["id"] = str(uuid.uuid4())
                    c.table("file_index").insert(row).execute()
                indexed += 1
            except Exception as e:
                logger.debug("File index upsert error: %s", e)

        return success_response(
            {"indexed": indexed, "total_sent": len(body.files)},
            f"{indexed} fichiers indexés",
        )
    except Exception as e:
        return error_response(str(e), 500)


@router.post("/search")
async def search_files(
    body: FileSearchRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Recherche sémantique dans les fichiers indexés."""
    try:
        c = get_supabase_admin()
        if not c:
            return error_response("Base de données non disponible", 503)

        # Recherche par nom (texte) + optionnellement par type
        query = (
            c.table("file_index")
            .select("id,file_name,file_path,file_type,file_size,mime_type,metadata,last_modified")
            .eq("user_id", user_id)
            .ilike("file_name", f"%{body.query}%")
        )

        if body.file_types:
            query = query.in_("file_type", body.file_types)

        res = query.limit(body.limit).execute()
        results = res.data or []

        return success_response(
            {"results": results, "query": body.query, "count": len(results)},
            "Recherche terminée",
        )
    except Exception as e:
        return error_response(str(e), 500)


@router.post("/upload")
async def upload_file(
    file: UploadFile = FastAPIFile(...),
    user_id: str = Depends(get_current_user_id),
):
    """Upload un fichier vers Supabase Storage."""
    try:
        file_bytes = await file.read()
        if len(file_bytes) > 100 * 1024 * 1024:  # 100MB max
            return error_response("Fichier trop volumineux (max 100MB)", 413)

        fname = file.filename or f"upload_{uuid.uuid4().hex[:8]}"
        content_type = file.content_type or "application/octet-stream"

        _, url = await storage_service.upload_bytes(
            file_bytes,
            f"user_files/{user_id}",
            fname,
            content_type,
        )

        return success_response(
            {"url": url, "file_name": fname, "size": len(file_bytes)},
            "Fichier uploadé",
        )
    except Exception as e:
        return error_response(str(e), 500)


@router.get("/index")
async def get_file_index(
    limit: int = Query(default=50, ge=1, le=500),
    file_type: Optional[str] = Query(default=None),
    user_id: str = Depends(get_current_user_id),
):
    """Retourne l'index complet des fichiers de l'utilisateur."""
    try:
        c = get_supabase_admin()
        if not c:
            return success_response([], "OK")

        query = (
            c.table("file_index")
            .select("*")
            .eq("user_id", user_id)
            .order("last_modified", desc=True)
        )
        if file_type:
            query = query.eq("file_type", file_type)

        res = query.limit(limit).execute()
        return success_response(res.data or [], "OK")
    except Exception as e:
        return error_response(str(e), 500)


@router.get("/download/{file_id}")
async def get_download_url(
    file_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Retourne l'URL de téléchargement d'un fichier indexé."""
    try:
        c = get_supabase_admin()
        if not c:
            return error_response("Base non disponible", 503)

        res = (
            c.table("file_index")
            .select("file_path,file_name")
            .eq("id", file_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not res.data:
            return error_response("Fichier introuvable", 404)

        file_data = res.data[0]
        return success_response(
            {"file_path": file_data["file_path"], "file_name": file_data["file_name"]},
            "OK",
        )
    except Exception as e:
        return error_response(str(e), 500)
