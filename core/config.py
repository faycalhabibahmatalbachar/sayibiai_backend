"""Configuration centralisée — variables d'environnement et paramètres applicatifs."""

from functools import lru_cache
from pathlib import Path
from typing import List, Tuple

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _env_files() -> Tuple[str, ...]:
    """
    Fichiers .env chargés dans l'ordre ; le dernier l'emporte.
    Prend en charge un `.env` à la racine `sayibi_backend/` et un ancien `sql/.env`.
    """
    root_env = _BACKEND_ROOT / ".env"
    sql_env = _BACKEND_ROOT / "sql" / ".env"
    paths: list[Path] = []
    if sql_env.is_file():
        paths.append(sql_env)
    if root_env.is_file():
        paths.append(root_env)
    if not paths:
        return (str(root_env),)
    return tuple(str(p) for p in paths)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_env_files(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Environnement
    environment: str = Field(
        default="development",
        validation_alias=AliasChoices("ENVIRONMENT", "environment"),
    )
    log_level: str = Field(
        default="INFO",
        validation_alias=AliasChoices("LOG_LEVEL", "log_level"),
    )

    # Clés LLM / services
    groq_api_key: str = ""
    gemini_api_key: str = ""
    # Ordre de priorité, séparé par des virgules (429/404/etc. → modèle suivant).
    gemini_models: str = Field(
        default=(
            "gemini-2.5-flash,"
            "gemini-3-flash,"
            "gemini-3.1-flash-lite,"
            "gemini-2.5-flash-lite,"
            "gemini-2.0-flash,"
            "gemini-1.5-flash"
        ),
        validation_alias=AliasChoices(
            "GEMINI_MODELS",
            "GEMINI_MODEL_PRIORITY",
            "gemini_models",
        ),
    )
    mistral_api_key: str = ""
    openai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("OPENAI_API_KEY", "openai_api_key"),
    )
    elevenlabs_api_key: str = ""
    tavily_api_key: str = ""
    serper_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("SERPER_API_KEY", "serper_api_key"),
    )

    supabase_url: str = ""
    supabase_key: str = Field(
        default="",
        validation_alias=AliasChoices("SUPABASE_ANON_KEY", "SUPABASE_KEY", "supabase_key"),
    )
    # URL publique du front Flutter web (lien de confirmation e-mail Supabase).
    # Déployer un site statique Render nommé ex. sayibi-web → https://sayibi-web.onrender.com
    public_app_url: str = Field(
        default="https://sayibi-web.onrender.com",
        validation_alias=AliasChoices("PUBLIC_APP_URL", "public_app_url"),
    )

    supabase_service_role_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SUPABASE_SERVICE_KEY",
            "SUPABASE_SERVICE_ROLE_KEY",
            "supabase_service_role_key",
        ),
    )

    upstash_redis_url: str = ""
    upstash_redis_token: str = ""

    pinecone_api_key: str = ""
    pinecone_index: str = Field(
        default="sayibi-memory",
        validation_alias=AliasChoices("PINECONE_INDEX_NAME", "PINECONE_INDEX", "pinecone_index"),
    )
    pinecone_host: str = ""
    pinecone_environment: str = Field(
        default="us-east-1",
        validation_alias=AliasChoices("PINECONE_ENVIRONMENT", "pinecone_environment"),
    )

    r2_account_id: str = ""
    r2_access_key: str = Field(
        default="",
        validation_alias=AliasChoices("R2_ACCESS_KEY_ID", "R2_ACCESS_KEY", "r2_access_key"),
    )
    r2_secret_key: str = Field(
        default="",
        validation_alias=AliasChoices("R2_SECRET_ACCESS_KEY", "R2_SECRET_KEY", "r2_secret_key"),
    )
    r2_bucket: str = Field(
        default="sayibi-files",
        validation_alias=AliasChoices("R2_BUCKET_NAME", "R2_BUCKET", "r2_bucket"),
    )
    r2_public_url: str = ""
    r2_jurisdiction: str = Field(
        default="",
        validation_alias=AliasChoices("R2_JURISDICTION", "r2_jurisdiction"),
    )
    r2_s3_endpoint: str = Field(
        default="",
        validation_alias=AliasChoices(
            "R2_S3_ENDPOINT",
            "R2_ENDPOINT",
            "r2_s3_endpoint",
        ),
    )

    jwt_secret: str = Field(
        default="dev-secret-change-in-production",
        validation_alias=AliasChoices("JWT_SECRET", "jwt_secret"),
    )
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30

    fcm_server_key: str = Field(
        default="",
        validation_alias=AliasChoices("FCM_SERVER_KEY", "fcm_server_key"),
    )
    firebase_credentials_path: str = Field(
        default="",
        validation_alias=AliasChoices(
            "FIREBASE_CREDENTIALS_PATH",
            "firebase_credentials_path",
        ),
    )
    firebase_credentials_json: str = Field(
        default="",
        validation_alias=AliasChoices(
            "FIREBASE_CREDENTIALS_JSON",
            "firebase_credentials_json",
        ),
    )

    sayibi_internal_secret: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SAYIBI_INTERNAL_SECRET",
            "sayibi_internal_secret",
        ),
    )

    cors_origins: str = "*"
    debug: bool = False
    trusted_hosts: str = Field(
        # *.onrender.com : accepte tout sous-domaine Render (ex. sayibi-backend-xxxx.onrender.com).
        default="*.onrender.com,sayibi-backend.onrender.com,sayibi-web.onrender.com,localhost,127.0.0.1",
        validation_alias=AliasChoices("TRUSTED_HOSTS", "trusted_hosts"),
    )

    kokoro_tts_url: str = ""

    def gemini_model_chain(self) -> List[str]:
        """Modèles Gemini dans l’ordre de bascule (hybride / fallback)."""
        return [p.strip() for p in (self.gemini_models or "").split(",") if p.strip()]

    @property
    def cors_origins_list(self) -> List[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def r2_endpoint(self) -> str:
        """Endpoint API S3-compatible (SigV4). Voir https://developers.cloudflare.com/r2/api/s3/tokens/"""
        custom = (self.r2_s3_endpoint or "").strip()
        if custom:
            return custom.rstrip("/")
        aid = (self.r2_account_id or "").strip()
        if not aid:
            return ""
        jur = (self.r2_jurisdiction or "").strip().lower()
        if jur in ("eu", "europe"):
            return f"https://{aid}.eu.r2.cloudflarestorage.com"
        if jur in ("fedramp", "fed-ramp"):
            return f"https://{aid}.fedramp.r2.cloudflarestorage.com"
        return f"https://{aid}.r2.cloudflarestorage.com"

    @property
    def trusted_hosts_list(self) -> List[str]:
        return [h.strip() for h in self.trusted_hosts.split(",") if h.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
