# Firebase Cloud Messaging v1 — Configuration complète

## Pourquoi l’API v1 ?

L’API **FCM HTTP v1** (recommandée par Google) n’utilise **pas** de « Server Key » au format legacy. Elle s’authentifie avec un **compte de service** Google (fichier JSON) et un **jeton OAuth2** (`Bearer`) pour appeler :

`POST https://fcm.googleapis.com/v1/projects/{project_id}/messages:send`

L’ancienne clé serveur (`FCM_SERVER_KEY`) correspond à l’API legacy et est déconseillée pour les nouveaux projets.

---

## Étape 1 — Télécharger le compte de service

1. Ouvrir [Firebase Console](https://console.firebase.google.com).
2. Sélectionner le projet **SAYIBI-AI** (ou le vôtre).
3. **Paramètres du projet** (icône engrenage) → **Comptes de service**.
4. Sous **Firebase Admin SDK**, cliquer sur **Générer une nouvelle clé privée**.
5. Enregistrer le fichier JSON (ex. `sayibi-ai-firebase-adminsdk-xxxxx.json`).

Ce fichier est **secret** : ne jamais le committer.

---

## Étape 2 — Placer le fichier côté backend (local)

```bash
mkdir -p sayibi_backend/credentials
cp ~/Downloads/sayibi-ai-firebase-adminsdk-xxxxx.json sayibi_backend/credentials/firebase-service-account.json
```

Sous Windows (PowerShell) :

```powershell
New-Item -ItemType Directory -Force -Path sayibi_backend\credentials
Copy-Item "$env:USERPROFILE\Downloads\sayibi-ai-firebase-adminsdk-xxxxx.json" "sayibi_backend\credentials\firebase-service-account.json"
```

---

## Étape 3 — Ignorer les secrets dans Git

Le dépôt inclut déjà `sayibi_backend/.gitignore` avec `credentials/` et `.env`. Vérifiez que le JSON n’est pas suivi :

```bash
git status
```

---

## Étape 4 — Variables d’environnement

Dans `.env` (à partir de `.env.example`) :

```env
# Chemin vers le JSON (développement local)
FIREBASE_CREDENTIALS_PATH=./credentials/firebase-service-account.json
```

Sur **Render.com** (ou tout hébergeur sans fichier persistant), préférez **une seule variable** contenant le JSON :

```env
FIREBASE_CREDENTIALS_JSON={"type":"service_account","project_id":"votre-projet",...}
```

- Copier **tout** le contenu du fichier JSON (une seule ligne ou minifié).
- Définir la variable comme **secrète** dans le tableau de bord.

---

## Étape 5 — Code backend (déjà intégré)

Le module `services/fcm_service.py` :

- charge les credentials depuis `FIREBASE_CREDENTIALS_JSON` ou `FIREBASE_CREDENTIALS_PATH` ;
- obtient un access token OAuth2 ;
- envoie des messages via l’API v1.

Endpoints associés :

- `GET /health` — champs `fcm_v1` et `fcm_legacy_key_set` ;
- `POST /api/v1/user/fcm-token` — enregistre le token appareil dans `users.fcm_token` (Supabase).

---

## Render.com — Variable `FIREBASE_CREDENTIALS_JSON`

1. Ouvrir le fichier JSON du compte de service dans un éditeur.
2. **Minifier** en une ligne (optionnel) ou coller le JSON multi-lignes si votre hébergeur l’accepte.
3. Render → **Environment** → **Add Environment Variable**  
   - **Key** : `FIREBASE_CREDENTIALS_JSON`  
   - **Value** : contenu JSON complet (sans guillemets autour du tout).
4. Redéployer le service.

---

## Vérification

1. `GET /health` → `"fcm_v1": true` lorsque les credentials sont valides.
2. Lancer `python test_apis.py` (avec `.env` chargé) → ligne **Firebase FCM** en OK.
3. **Test utilisateur connecté** (JWT requis) — envoie au token enregistré en base :
   ```bash
   curl -X POST "https://VOTRE_API/api/v1/user/notify-test" \
     -H "Authorization: Bearer VOTRE_ACCESS_JWT" \
     -H "Content-Type: application/json" \
     -d "{\"title\":\"Test SAYIBI\",\"body\":\"Hello FCM\"}"
   ```
   Prérequis : l’app a d’abord appelé `POST /api/v1/user/fcm-token` avec le jeton FCM de l’appareil.

4. **Test interne** (jeton FCM arbitraire, sans JWT) — définir `SAYIBI_INTERNAL_SECRET` sur le serveur :
   ```bash
   curl -X POST "https://VOTRE_API/api/v1/internal/fcm-test" \
     -H "X-Sayibi-Internal-Secret: VOTRE_SECRET_INTERNE" \
     -H "Content-Type: application/json" \
     -d "{\"fcm_token\":\"TOKEN_FCM_DEVICE\",\"title\":\"Test\",\"body\":\"Interne\"}"
   ```
   Ne jamais exposer ce secret côté client mobile ; réservé à un script admin / Postman / CI.

---

## Dépannage

| Problème | Piste |
|----------|--------|
| `fcm_v1: false` | Variables manquantes ou JSON invalide ; chemin fichier incorrect sous Docker/Render. |
| `403` / `401` sur FCM | Compte de service sans rôle adapté ; API **Firebase Cloud Messaging API** activée dans Google Cloud Console. |
| `404` projet | `project_id` dans le JSON ≠ projet Firebase utilisé par l’app mobile. |

Dans Google Cloud Console : **APIs & Services** → activer **Firebase Cloud Messaging API** (et **FCM** selon le libellé du projet).
