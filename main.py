"""Point d'entrée FastAPI — ChadGpt backend."""

import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from core.config import get_settings
from core.database import init_db
from middleware.logger import RequestLoggingMiddleware, setup_logging
from middleware.rate_limiter import RateLimitMiddleware
from middleware.user_context import UserContextMiddleware
from services import fcm_service
from routers import alarm, agent, agent_actions, auth, chat, documents, generate, image, internal, omni, search, user, voice
from routers import media, social, surveillance, avatar, files, proactivity


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    setup_logging(s.debug, s.log_level)
    await init_db()
    yield


_settings = get_settings()
_show_docs = _settings.environment == "development" or _settings.debug

app = FastAPI(
    title="ChadGpt API",
    description="Backend multilingue FR/AR/EN — chat, documents, voix, génération, recherche (ChadGpt).",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if _show_docs else None,
    redoc_url="/redoc" if _show_docs else None,
    openapi_url="/openapi.json" if _show_docs else None,
)

settings = get_settings()

# Ordre : le **dernier** add_middleware est le plus **externe** — CORS en dernier pour que
# toutes les réponses (y compris 429 du rate limit) reçoivent Access-Control-Allow-Origin.
if settings.environment == "production":
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.trusted_hosts_list,
    )

app.add_middleware(UserContextMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RateLimitMiddleware)

# Origines explicites : variable CORS_ORIGINS (Render / .env).
# Regex en complément : Flutter web en local utilise souvent http://localhost:PORT —
# inutile de lister chaque port ; évite les erreurs « No Access-Control-Allow-Origin »
# si l’env distant n’inclut pas exactement le port (8080, 5173, etc.).
_LOCALHOST_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_origin_regex=_LOCALHOST_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API = "/api/v1"
app.include_router(auth.router, prefix=f"{API}")
app.include_router(agent.router, prefix=f"{API}")
app.include_router(agent_actions.router, prefix=f"{API}")
app.include_router(chat.router, prefix=f"{API}")
app.include_router(voice.router, prefix=f"{API}")
app.include_router(alarm.router, prefix=f"{API}")
app.include_router(documents.router, prefix=f"{API}")
app.include_router(generate.router, prefix=f"{API}")
app.include_router(image.router, prefix=f"{API}")
app.include_router(search.router, prefix=f"{API}")
app.include_router(user.router, prefix=f"{API}")
app.include_router(internal.router, prefix=f"{API}")
app.include_router(omni.router, prefix=f"{API}")
app.include_router(media.router, prefix=f"{API}")
app.include_router(social.router, prefix=f"{API}")
app.include_router(surveillance.router, prefix=f"{API}")
app.include_router(avatar.router, prefix=f"{API}")
app.include_router(files.router, prefix=f"{API}")
app.include_router(proactivity.router, prefix=f"{API}")


@app.get("/health")
async def health():
    """Santé du service et disponibilité des intégrations."""
    s = get_settings()
    fcm_v1 = False
    try:
        fcm_v1 = fcm_service.fcm_v1_configured()
    except Exception:
        fcm_v1 = False
    return {
        "status": "ok",
        "supabase": bool(s.supabase_url and s.supabase_key),
        "groq": bool(s.groq_api_key),
        "gemini": bool(s.gemini_api_key),
        "mistral": bool(s.mistral_api_key),
        "redis": bool(s.upstash_redis_url),
        "pinecone": bool(s.pinecone_api_key),
        "r2": bool(s.r2_account_id and s.r2_access_key),
        "fcm_v1": fcm_v1,
        "fcm_legacy_key_set": bool(s.fcm_server_key),
    }


@app.get("/")
async def root():
    s = get_settings()
    docs = "/docs" if (s.environment == "development" or s.debug) else None
    return {"name": "ChadGpt", "docs": docs, "health": "/health"}


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "data": exc.errors(),
            "message": "Validation des entrées",
            "code": 422,
        },
    )


@app.exception_handler(Exception)
async def global_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        detail = exc.detail
        if not isinstance(detail, str):
            detail = str(detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "data": None,
                "message": detail,
                "code": exc.status_code,
            },
        )
    if get_settings().debug:
        tb = traceback.format_exc()
    else:
        tb = str(exc)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "data": None,
            "message": tb if get_settings().debug else "Erreur interne du serveur",
            "code": 500,
        },
    )
