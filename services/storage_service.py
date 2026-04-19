"""Stockage fichiers — Cloudflare R2 (API S3 compatible)."""

import uuid
from typing import Optional, Tuple

import boto3
from botocore.config import Config

from core.config import get_settings


def _client():
    settings = get_settings()
    if not all(
        [
            settings.r2_account_id,
            settings.r2_access_key,
            settings.r2_secret_key,
            settings.r2_bucket,
        ]
    ):
        return None
    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint,
        aws_access_key_id=settings.r2_access_key,
        aws_secret_access_key=settings.r2_secret_key,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        ),
        region_name="auto",
    )


async def upload_bytes(
    data: bytes,
    key_prefix: str,
    filename: str,
    content_type: str,
) -> Tuple[str, str]:
    """
    Upload vers R2. Retourne (clé objet, URL publique ou endpoint interne).
    Sans R2 configuré, retourne une clé locale fictive (base64 refusée côté prod).
    """
    settings = get_settings()
    safe_name = filename.replace(" ", "_")
    object_key = f"{key_prefix}/{uuid.uuid4().hex}_{safe_name}"
    client = _client()
    if not client:
        # Mode développement : pas d'upload cloud
        return object_key, f"local://{object_key}"

    client.put_object(
        Bucket=settings.r2_bucket,
        Key=object_key,
        Body=data,
        ContentType=content_type,
    )
    public = settings.r2_public_url.rstrip("/") if settings.r2_public_url else ""
    url = f"{public}/{object_key}" if public else f"r2://{settings.r2_bucket}/{object_key}"
    return object_key, url


def get_presigned_url(object_key: str, expires_in: int = 3600) -> Optional[str]:
    """URL présignée de téléchargement (GET)."""
    settings = get_settings()
    client = _client()
    if not client:
        return None
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.r2_bucket, "Key": object_key},
        ExpiresIn=expires_in,
    )
