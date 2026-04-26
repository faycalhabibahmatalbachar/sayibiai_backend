# SAYIBI AI — Guide de déploiement complet

Ce guide couvre le dépôt GitHub, Render.com, variables d’environnement, Firebase FCM v1, et la vérification post-déploiement.

---

## 1. Prérequis

- Compte [GitHub](https://github.com)
- [GitHub CLI](https://cli.github.com/) (`gh`) pour le script optionnel
- Compte [Render.com](https://render.com) lié à GitHub
- Projet [Supabase](https://supabase.com) + schéma `sql/complete_schema.sql` exécuté
- Clés API (Groq, Gemini, Mistral, Tavily, etc.) — voir `.env.example`
- Compte de service **Firebase** pour FCM v1 — voir `FIREBASE_FCM_SETUP.md`

---

## 2. Dépôt GitHub

### Option A — Script (Linux / macOS / Git Bash Windows)

```bash
cd sayibi_backend
chmod +x deploy/setup_github_repo.sh
./deploy/setup_github_repo.sh
```

Variables optionnelles :

- `SAYIBI_GH_REPO_NAME` — nom du dépôt (défaut : `sayibi-backend`)
- `SAYIBI_GH_DESC` — description
- `SAYIBI_GH_VISIBILITY` — `public` ou `private`

### Option B — Manuel

```bash
cd sayibi_backend
git init
git branch -M main
git remote add origin https://github.com/VOTRE_USER/sayibi-backend.git
git add .
git commit -m "Initial commit: SAYIBI AI backend"
git push -u origin main
```

Ne commitez **jamais** `.env` ni `credentials/*.json`.

---

## 3. Render.com — Web Service

### 3.1 Via Blueprint

1. Pousser `render.yaml` à la racine du dépôt (déjà présent sous `sayibi_backend/render.yaml` — à la racine du repo si le repo **est** le backend seul).
2. Render → **New** → **Blueprint**.
3. Sélectionner le dépôt et le fichier `render.yaml`.
4. Renseigner les variables marquées `sync: false` dans le tableau de bord (secrets).

### 3.2 Via Web Service manuel

1. **New** → **Web Service** → connecter le dépôt GitHub.
2. **Root Directory** : `sayibi_backend` si le backend est dans un sous-dossier du monorepo.
3. **Build command** : `pip install -r requirements.txt`
4. **Start command** : `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. **Health check path** : `/health`
6. **Environment** : `production`
7. Ajouter toutes les variables de `.env.example` (valeurs réelles, secrètes).

### 3.3 FCM sur Render

- Préférer **`FIREBASE_CREDENTIALS_JSON`** (contenu complet du JSON compte de service) comme variable secrète.
- Voir `FIREBASE_FCM_SETUP.md`.

---

## 4. Variables d’environnement essentielles

| Variable | Rôle |
|----------|------|
| `ENVIRONMENT` | `production` sur Render |
| `JWT_SECRET` | Secret fort pour JWT |
| `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY` | Base + admin |
| `GROQ_API_KEY`, `GEMINI_API_KEY`, `MISTRAL_API_KEY` | LLM |
| `TAVILY_API_KEY` | Recherche web |
| `UPSTASH_REDIS_URL`, `UPSTASH_REDIS_TOKEN` | Rate limit / cache |
| `PINECONE_API_KEY`, `PINECONE_INDEX_NAME` | Vecteurs |
| `R2_*` | Stockage fichiers |
| `FIREBASE_CREDENTIALS_JSON` ou `FIREBASE_CREDENTIALS_PATH` | FCM v1 |
| `CORS_ORIGINS` | Origines autorisées (ex. app Flutter, web) |
| `TRUSTED_HOSTS` | Hôtes acceptés (middleware production) |

---

## 5. Vérification après déploiement

### 5.1 Santé HTTP

```bash
curl -sS https://VOTRE_SERVICE.onrender.com/health
```

Réponse attendue : JSON avec `status`, `fcm_v1`, intégrations booléennes.

### 5.2 Script de tests d’intégration

En local (avec `.env` rempli) :

```bash
pip install -r requirements.txt -r requirements-test.txt
python test_apis.py
```

Pour tester le service déployé :

```env
SAYIBI_DEPLOY_URL=https://VOTRE_SERVICE.onrender.com
```

Puis relancer `python test_apis.py` (vérifie notamment `GET /health`).

### 5.3 Documentation API

En `development` ou `DEBUG=true`, Swagger est disponible sur `/docs`. En production pure, les docs sont désactivées par défaut (`main.py`).

---

## 6. Fichiers de référence

| Fichier | Contenu |
|---------|---------|
| `SERVICES_SETUP.md` | Obtenir chaque clé / service |
| `FIREBASE_FCM_SETUP.md` | FCM HTTP v1 |
| `FEATURES_SUMMARY.md` | Fonctionnalités |
| `sql/complete_schema.sql` | Schéma Supabase |
| `deploy/setup_github_repo.sh` | Automatisation GitHub |
| `render.yaml` | Blueprint Render |

---

## 7. Dépannage rapide

| Symptôme | Action |
|----------|--------|
| 502 / timeout au build | Vérifier `requirements.txt`, versions Python Render. |
| CORS | Ajouter l’origine exacte dans `CORS_ORIGINS`. |
| Trusted host | Ajouter le hostname Render dans `TRUSTED_HOSTS`. |
| `fcm_v1: false` | JSON manquant ou invalide ; activer API FCM dans Google Cloud. |
| Redis | URL Upstash **HTTPS** pour les tests REST ; client Python peut utiliser `rediss://`. |

---

## 8. Responsable technique

**Faycal Habib Ahmat** — SAYIBI Technologies.
