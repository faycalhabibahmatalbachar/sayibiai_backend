#!/usr/bin/env bash
# SAYIBI AI — Création du dépôt GitHub et push initial (GitHub CLI)
# Usage : depuis sayibi_backend/
#   chmod +x deploy/setup_github_repo.sh
#   ./deploy/setup_github_repo.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$BACKEND_ROOT"

echo "🚀 SAYIBI AI — Setup dépôt GitHub (backend)"
echo "============================================="
echo "Répertoire : $BACKEND_ROOT"
echo ""

if ! command -v gh &>/dev/null; then
  echo "❌ GitHub CLI (gh) n'est pas installé."
  echo "   https://cli.github.com/"
  exit 1
fi

echo "📝 Vérification de l'authentification GitHub..."
gh auth status || gh auth login

REPO_NAME="${SAYIBI_GH_REPO_NAME:-sayibi-backend}"
REPO_DESC="${SAYIBI_GH_REPO_DESC:-SAYIBI AI Backend - FastAPI + Supabase + LLM APIs}"
VISIBILITY="${SAYIBI_GH_VISIBILITY:-public}"

if [ ! -d .git ]; then
  echo "📂 git init..."
  git init
  git branch -M main 2>/dev/null || true
fi

if [ ! -f .gitignore ]; then
  echo "⚠️  .gitignore absent à la racine backend — copiez le fichier depuis le dépôt SAYIBI ou créez-le."
fi

echo "📦 Création / liaison du dépôt : $REPO_NAME ($VISIBILITY)..."
# Si le remote origin existe déjà, ne pas recréer le repo distant
if git remote get-url origin &>/dev/null; then
  echo "   Remote origin déjà configuré : $(git remote get-url origin)"
else
  gh repo create "$REPO_NAME" \
    --"$VISIBILITY" \
    --description "$REPO_DESC" \
    --source=. \
    --remote=origin \
    --push
fi

LOGIN="$(gh api user -q .login)"
echo "✅ Dépôt : https://github.com/$LOGIN/$REPO_NAME"

if ! git remote get-url origin &>/dev/null; then
  git remote add origin "https://github.com/$LOGIN/$REPO_NAME.git"
fi

git add -A
if git diff --cached --quiet; then
  echo "ℹ️  Rien à committer (working tree clean)."
else
  git commit -m "chore: SAYIBI AI backend — configuration initiale" || true
  git push -u origin main
fi

echo ""
echo "✅ Terminé."
echo ""
echo "📋 Étapes suivantes :"
echo "  1. https://render.com → New → Web Service"
echo "  2. Connecter le dépôt : $REPO_NAME"
echo "  3. Build : pip install -r requirements.txt"
echo "  4. Start : uvicorn main:app --host 0.0.0.0 --port \$PORT"
echo "  5. Variables d'environnement : voir .env.example et DEPLOYMENT_GUIDE.md"
echo ""
