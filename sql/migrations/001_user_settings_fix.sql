-- Corrige PUT /api/v1/user/settings (500) : colonne manquante + contrainte model_preference trop stricite.
-- Exécuter une fois sur Supabase : SQL Editor → Run.

ALTER TABLE public.users ADD COLUMN IF NOT EXISTS notifications BOOLEAN DEFAULT true;

ALTER TABLE public.users DROP CONSTRAINT IF EXISTS users_model_preference_check;

COMMENT ON COLUMN public.users.notifications IS 'Préférences notifications push / in-app';
COMMENT ON COLUMN public.users.model_preference IS 'auto | groq | gemini | mistral | sayibi-* | autre';
