# SAYIBI AI — Backend FastAPI

API REST pour l’application SAYIBI AI : chat multilingue, documents (RAG), voix, génération de fichiers, recherche web, profil utilisateur.

## Prérequis

- Python 3.11+
- Comptes / clés (selon les fonctionnalités) : Groq, Google Gemini, Mistral, Supabase, Redis Upstash, Pinecone, Cloudflare R2, Tavily, ElevenLabs (optionnel)

## Installation locale

```bash
cd sayibi_backend
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
copy .env.example .env
```

Renseigner `.env` avec vos clés.

### Windows + Python 3.13

Si `pip install` échoue sur **PyMuPDF** avec « Unable to find Visual Studio », c’est une ancienne version qui compilait MuPDF depuis les sources. Le fichier `requirements.txt` du dépôt impose une version avec **roue précompilée** (`PyMuPDF>=1.24`). Mettez à jour le dépôt puis :

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Utilisez de préférence un **environnement virtuel** (`.venv`) pour ne pas mélanger avec le Python système.

## Lancer le serveur

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

- Documentation interactive : http://localhost:8000/docs  
- Santé : http://localhost:8000/health  

## Préfixe des routes

Toutes les routes métier sont sous **`/api/v1`** (ex. `/api/v1/chat/message`).

## Base Supabase

Schéma complet (RLS, Storage, trigger `auth.users` → `public.users`) : exécuter **`sql/complete_schema.sql`** dans l’éditeur SQL Supabase.  
(Schéma minimal historique : `sql/schema.sql`.)

## Documentation

| Fichier | Description |
|---------|-------------|
| `DEPLOYMENT_GUIDE.md` | GitHub, Render, variables, vérifications |
| `FIREBASE_FCM_SETUP.md` | FCM HTTP v1 (compte de service) |
| `FEATURES_SUMMARY.md` | Fonctionnalités backend |
| `SERVICES_SETUP.md` | Obtenir les clés API |
| `render.yaml` | Blueprint Render.com |

## Tests d’intégration (clés externes)

```bash
pip install -r requirements.txt -r requirements-test.txt
python test_apis.py
```

Sans ces tables ou clés, le chat et l’usage fonctionnent en mode dégradé.

## Docker

```bash
docker build -t sayibi-backend .
docker run -p 8000:8000 --env-file .env sayibi-backend
```

## Notes

- Les jetons d’accès sont des JWT signés avec `JWT_SECRET` ; les refresh tokens sont stockés dans Redis (ou en mémoire si Redis absent — **développement uniquement**).
- Pinecone nécessite des embeddings Mistral pour rester aligné sur la dimension de l’index.
