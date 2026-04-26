# SAYIBI AI — Résumé des fonctionnalités (backend)

## Authentification et utilisateurs

**Endpoints** (`/api/v1/auth/`) :

- Inscription, connexion, refresh JWT, OAuth Google (via Supabase selon implémentation actuelle).

**Comportement** :

- JWT applicatif (access + refresh), profils `public.users`, RLS côté Supabase lorsque le schéma `complete_schema.sql` est appliqué.

---

## Chat IA multilingue

**Endpoints** (`/api/v1/chat/`) :

- `POST /message` — message et réponse.
- `POST /stream` — flux SSE.
- `GET /history/{session_id}` — historique paginé.
- `GET /sessions` — liste des sessions.
- `DELETE /session/{session_id}` — suppression session + messages.

**Comportement** :

- Routage LLM (Groq / Gemini / Mistral) via `services/ai_router.py`.
- Persistance : tables `chat_sessions` et `messages` (schéma complet).

---

## Voix

**Endpoints** (`/api/v1/voice/`) :

- Transcription (Groq Whisper) et synthèse (ElevenLabs / Kokoro selon config).

---

## Documents

**Endpoints** (`/api/v1/documents/`) :

- Upload, questions RAG, résumé — avec extraction PyMuPDF / docx / Gemini vision, stockage R2, Pinecone.

---

## Génération de fichiers

**Endpoints** (`/api/v1/generate/`) :

- CV, lettre, rapport, Excel, export depuis le chat — fichiers envoyés sur R2 et métadonnées en `generated_files`.

---

## Recherche web

**Endpoints** (`/api/v1/search/`) :

- Recherche Tavily (et fallbacks selon code).

---

## Profil et usage

**Endpoints** (`/api/v1/user/`) :

- `GET /profile`, `PUT /settings`, `GET /usage`, `GET /files`, `DELETE /files/{id}`.
- `POST /fcm-token` — enregistre le jeton FCM appareil (`users.fcm_token`).
- `POST /notify-test` — envoie une notification FCM de test au token enregistré (JWT requis).

**Interne (ops / QA)** — `POST /api/v1/internal/fcm-test` avec l’en-tête `X-Sayibi-Internal-Secret` (variable `SAYIBI_INTERNAL_SECRET` côté serveur). Ne jamais exposer ce secret dans l’app mobile.

---

## Notifications push (FCM v1)

- Module `services/fcm_service.py` (OAuth2 + API HTTP v1).
- Configuration : `FIREBASE_FCM_SETUP.md`.
- Santé : `GET /health` expose `fcm_v1` et `fcm_legacy_key_set`.

---

## Sécurité et performance

- Rate limiting Redis, CORS, validation Pydantic, logs requêtes.
- Trusted hosts en production.

---

## Base de données et stockage

- Schéma détaillé : `sql/complete_schema.sql`.
- Buckets Storage : `user-avatars`, `uploaded-documents`, `generated-files`.

---

## Déploiement

- **Render** : `render.yaml`, guide `DEPLOYMENT_GUIDE.md`.
- **Secrets** : jamais committer `.env` ni JSON compte de service.

---

## Piste d’évolution

Workspaces multi-tenant, API keys publiques, agents autonomes, facturation, 2FA, etc. — à prioriser selon produit.

---

## Modèle de prompt pour approfondir une fonctionnalité (Cursor)

Utiliser ce canevas dans le chat :

```text
I need detailed implementation for [FEATURE_NAME] in SAYIBI AI backend.
Please provide:

- Complete file code with all edge cases handled
- Error handling for every possible failure scenario
- Unit tests (pytest) covering happy path + error cases
- Integration test with real API mocking
- Documentation with usage examples
- Performance optimization notes
- Security considerations specific to this feature

Feature to detail: [CHOOSE ONE]

Examples: Chat streaming, document upload hardening, advanced RAG, FCM batch sends,
admin endpoints, Stripe billing, webhooks, Alembic migrations, Sentry monitoring.
```

Demander explicitement **type hints**, **logging**, **retry / backoff**, **validation**, **rate limits** et **dégradation gracieuse** si vous ciblez la production.
