# 🔑 Services et Clés API — Guide Complet

## 1. Supabase (Base de données + Auth + Storage)

### Création projet
1. Aller sur https://supabase.com → "New Project"
2. Nom : `sayibi-ai-prod`
3. Database Password : générer un mot de passe fort (sauvegarder)
4. Région : Europe (Frankfurt) ou US East (selon localisation)

### Récupération des clés
- Dashboard → Settings → API
  - `SUPABASE_URL` : https://xxxxx.supabase.co
  - `SUPABASE_ANON_KEY` : eyJhbGc... (clé publique)
  - `SUPABASE_SERVICE_KEY` : eyJhbGc... (clé admin, JAMAIS exposée côté client)

### Configuration Auth
- Dashboard → Authentication → Providers
  - Email : activé par défaut
  - Google OAuth :
    1. Créer projet Google Cloud Console
    2. APIs & Services → Credentials → OAuth 2.0 Client IDs
    3. Copier Client ID + Secret dans Supabase
  - Phone (optionnel) : intégration Twilio

### Storage Buckets
- Dashboard → Storage → Create bucket
  - `user-avatars` (public)
  - `uploaded-documents` (private, RLS)
  - `generated-files` (private, RLS)

---

## 2. Groq (LLM ultra-rapide + Whisper)

1. https://console.groq.com → Sign up
2. API Keys → Create API Key
3. Copier `GROQ_API_KEY` : gsk_...
4. Free tier : ~14 400 requêtes/jour

---

## 3. Google AI Studio (Gemini)

1. https://aistudio.google.com/app/apikey
2. Créer un projet Google Cloud si nécessaire
3. Get API Key → Copier `GEMINI_API_KEY`
4. Free tier : 1 500 req/jour (Flash), 15 req/min

---

## 4. Mistral AI

1. https://console.mistral.ai → Sign up
2. API Keys → Create
3. Copier `MISTRAL_API_KEY`
4. Free tier disponible (limité)

---

## 5. Tavily (Recherche Web IA)

1. https://tavily.com → Sign up
2. API → Get API Key
3. Copier `TAVILY_API_KEY`
4. Free : 1 000 recherches/mois

---

## 6. ElevenLabs (TTS haute qualité)

1. https://elevenlabs.io → Sign up
2. Profile → API Key
3. Copier `ELEVENLABS_API_KEY`
4. Free : 10 000 caractères/mois

---

## 7. Upstash Redis (Rate Limiting + Cache)

1. https://console.upstash.com → Create Database
2. Type : Regional, Region : EU-Central-1
3. Copier :
   - `UPSTASH_REDIS_URL` : redis://...
   - `UPSTASH_REDIS_TOKEN` : AX...

---

## 8. Pinecone (Base vectorielle)

1. https://app.pinecone.io → Sign up
2. Create Index :
   - Name : `sayibi-memory`
   - Dimensions : 1024 (Mistral embeddings)
   - Metric : cosine
   - Serverless (région AWS us-east-1)
3. API Keys → Copier `PINECONE_API_KEY`

---

## 9. Cloudflare R2 (Stockage fichiers)

Documentation officielle (jetons API S3) : [R2 API tokens](https://developers.cloudflare.com/r2/api/s3/tokens/)

1. **Activer R2** sur le compte Cloudflare (offre avec quota ; les jetons API ne sont disponibles qu’avec R2 activé).
2. Dashboard → **R2** → créer un bucket (ex. `sayibi-files`).
3. Sur la page **R2 Overview**, section **Account details** :
   - **`R2_ACCOUNT_ID`** : identifiant du compte (32 caractères hex), pas une clé API.
   - **Manage R2 API Tokens** → **Create Account API token** ou **Create User API token**.
4. Permissions : **Object Read & Write** (limité à ce bucket) ou **Admin Read & Write** si besoin de créer des buckets par API.
5. Après création : copier **Access Key ID** et **Secret Access Key** (affiché **une seule fois**) → `R2_ACCESS_KEY_ID` et `R2_SECRET_ACCESS_KEY`.

   Ce ne sont **pas** la « Global API Key » ni un token Workers générique : il faut impérativement un jeton **R2** comme ci-dessus.

   **Important** : l’**Access Key ID** R2 (API S3) fait **exactement 32 caractères** (hex). Si votre variable fait ~40–50+ caractères, vous avez collé un **autre** type de jeton (ex. API Token au format JWT Cloudflare) : retournez dans **R2 → Manage R2 API Tokens**, créez un jeton avec permissions **Object Read & Write** sur le bucket, et recopiez les deux clés affichées à la création.

6. **Endpoint S3** utilisé par le backend (et `test_apis.py`) :
   - Par défaut : `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`
   - Si le bucket est en **juridiction EU** : utiliser l’endpoint EU et dans `.env` : `R2_JURISDICTION=eu`  
     (sinon `HeadBucket` peut répondre **400 Bad Request**).  
     Doc : [jurisdictions R2](https://developers.cloudflare.com/r2/reference/data-location/).
   - Surcharge manuelle : `R2_S3_ENDPOINT=https://<ACCOUNT_ID>.eu.r2.cloudflarestorage.com` (ou l’URL exacte indiquée par Cloudflare).

7. **`R2_PUBLIC_URL`** : domaine public du bucket (onglet **Settings** du bucket → **Public access** / **r2.dev** / domaine custom). Optionnel pour les tests S3 ; utile pour les URLs affichées aux utilisateurs.

8. Fichier **`.env`** : placer les variables dans **`sayibi_backend/.env`** (recommandé). Un fichier `sql/.env` est encore chargé en secours mais le chemin racine est préférable.

---

## 10. Firebase Cloud Messaging (Push Notifications)

1. https://console.firebase.google.com → Add Project
2. Project name : `SAYIBI-AI`
3. Android App :
   - Package name : `com.sayibi.ai`
   - Download `google-services.json` → placer dans `sayibi_flutter/android/app/`
4. iOS App :
   - Bundle ID : `com.sayibi.ai`
   - Download `GoogleService-Info.plist` → placer dans `sayibi_flutter/ios/Runner/`
5. **Backend (recommandé)** : API **FCM HTTP v1** avec **compte de service** (JSON), pas la legacy « Server Key ». Procédure détaillée : **`FIREBASE_FCM_SETUP.md`**. Variables : `FIREBASE_CREDENTIALS_PATH` ou `FIREBASE_CREDENTIALS_JSON`.
6. Activer **Firebase Cloud Messaging API** dans Google Cloud Console.

---

## 11. Render.com (Backend Hosting)

1. https://render.com → Sign up (avec GitHub)
2. New → Web Service
3. Connect votre repo GitHub `sayibi_backend`
4. Configuration :
   - Name : `sayibi-backend`
   - Region : Frankfurt (EU) ou Oregon (US)
   - Branch : `main`
   - Runtime : Python 3
   - Build Command : `pip install -r requirements.txt`
   - Start Command : `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Environment Variables → ajouter toutes les clés (voir .env)
6. Free tier : 750h/mois (app se met en veille après 15min inactivité)

---

## 12. JWT Secret (Génération)

```python
import secrets
JWT_SECRET = secrets.token_urlsafe(64)
print(JWT_SECRET)  # Copier dans .env
```

---

## ✅ Checklist Complète

- [ ] Supabase projet créé + clés récupérées
- [ ] SQL schema exécuté (voir `sql/complete_schema.sql` sur projet neuf ; `sql/schema.sql` reste un schéma minimal historique)
- [ ] Buckets storage créés avec RLS
- [ ] Groq API key
- [ ] Gemini API key
- [ ] Mistral API key
- [ ] Tavily API key
- [ ] ElevenLabs API key
- [ ] Upstash Redis créé
- [ ] Pinecone index créé (dimension 1024)
- [ ] Cloudflare R2 bucket + API token
- [ ] Firebase projet créé + FCM activé + compte de service JSON (`FIREBASE_FCM_SETUP.md`)
- [ ] google-services.json et GoogleService-Info.plist téléchargés (Flutter)
- [ ] Render.com web service créé
- [ ] .env backend rempli avec toutes les clés
- [ ] .env Flutter rempli (API_BASE_URL)
