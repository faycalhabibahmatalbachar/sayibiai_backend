-- ============================================================
-- SAYIBI AI — Schema Supabase Complet
-- Idempotent : ré-exécutable (IF NOT EXISTS, DROP … IF EXISTS).
-- Projet neuf : tout le fichier. Déjà en place : seules les parties
-- manquantes s’appliquent ; triggers / policies sont recréés si besoin.
-- ============================================================

-- Extension pour UUID
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Extension pour vecteurs (si RAG côté Supabase)
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================
-- TABLE : users (synchronisée avec auth.users)
-- ============================================================
CREATE TABLE IF NOT EXISTS public.users (
  id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email TEXT UNIQUE NOT NULL,
  full_name TEXT,
  avatar_url TEXT,
  language TEXT DEFAULT 'fr' CHECK (language IN ('fr', 'ar', 'en')),
  plan TEXT DEFAULT 'free' CHECK (plan IN ('free', 'pro', 'enterprise')),
  model_preference TEXT DEFAULT 'auto' CHECK (model_preference IN ('auto', 'groq', 'gemini', 'mistral')),
  theme TEXT DEFAULT 'dark' CHECK (theme IN ('light', 'dark')),
  fcm_token TEXT, -- Firebase Cloud Messaging token
  total_tokens_used BIGINT DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index
CREATE INDEX IF NOT EXISTS idx_users_email ON public.users(email);
CREATE INDEX IF NOT EXISTS idx_users_created_at ON public.users(created_at DESC);

-- Trigger pour updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS users_updated_at ON public.users;
CREATE TRIGGER users_updated_at BEFORE UPDATE ON public.users
FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- TABLE : chat_sessions
-- ============================================================
CREATE TABLE IF NOT EXISTS public.chat_sessions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES public.users(id) ON DELETE CASCADE NOT NULL,
  title TEXT DEFAULT 'Nouvelle conversation',
  model_used TEXT, -- 'groq', 'gemini', 'mistral'
  language TEXT DEFAULT 'fr',
  total_messages INT DEFAULT 0,
  total_tokens INT DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON public.chat_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON public.chat_sessions(created_at DESC);

DROP TRIGGER IF EXISTS sessions_updated_at ON public.chat_sessions;
CREATE TRIGGER sessions_updated_at BEFORE UPDATE ON public.chat_sessions
FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- TABLE : messages
-- ============================================================
CREATE TABLE IF NOT EXISTS public.messages (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  session_id UUID REFERENCES public.chat_sessions(id) ON DELETE CASCADE NOT NULL,
  role TEXT CHECK (role IN ('user', 'assistant', 'system')) NOT NULL,
  content TEXT NOT NULL,
  tokens INT DEFAULT 0,
  model_used TEXT,
  has_image BOOLEAN DEFAULT FALSE,
  image_urls TEXT[], -- Array d'URLs d'images affichées dans le message
  metadata JSONB, -- Pour stocker données supplémentaires (sources web, etc.)
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_session_id ON public.messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON public.messages(created_at DESC);

-- ============================================================
-- TABLE : documents (fichiers uploadés)
-- ============================================================
CREATE TABLE IF NOT EXISTS public.documents (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES public.users(id) ON DELETE CASCADE NOT NULL,
  filename TEXT NOT NULL,
  file_type TEXT, -- 'pdf', 'docx', 'xlsx', 'image'
  file_size BIGINT, -- en bytes
  storage_path TEXT NOT NULL, -- Chemin dans Supabase Storage ou R2
  extracted_text TEXT, -- Texte extrait du document
  page_count INT,
  embedding_id TEXT, -- ID dans Pinecone si vecteurs créés
  metadata JSONB, -- Informations supplémentaires
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_documents_user_id ON public.documents(user_id);
CREATE INDEX IF NOT EXISTS idx_documents_created_at ON public.documents(created_at DESC);

-- ============================================================
-- TABLE : generated_files (fichiers créés par l'IA)
-- ============================================================
CREATE TABLE IF NOT EXISTS public.generated_files (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES public.users(id) ON DELETE CASCADE NOT NULL,
  file_type TEXT CHECK (file_type IN ('cv', 'letter', 'report', 'excel', 'other')) NOT NULL,
  filename TEXT NOT NULL,
  storage_path TEXT NOT NULL, -- Chemin R2 ou Supabase Storage
  prompt_used TEXT, -- Prompt original ayant généré le fichier
  session_id UUID REFERENCES public.chat_sessions(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_generated_files_user_id ON public.generated_files(user_id);
CREATE INDEX IF NOT EXISTS idx_generated_files_created_at ON public.generated_files(created_at DESC);

-- ============================================================
-- TABLE : usage_logs (tracking consommation)
-- ============================================================
CREATE TABLE IF NOT EXISTS public.usage_logs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES public.users(id) ON DELETE CASCADE NOT NULL,
  endpoint TEXT NOT NULL, -- '/chat/message', '/voice/transcribe', etc.
  model_used TEXT,
  tokens_used INT DEFAULT 0,
  request_duration_ms INT, -- Temps de réponse en millisecondes
  status_code INT, -- 200, 400, 500, etc.
  error_message TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_usage_logs_user_id ON public.usage_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_usage_logs_created_at ON public.usage_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_usage_logs_endpoint ON public.usage_logs(endpoint);

-- ============================================================
-- TABLE : web_search_cache (cache recherches web)
-- ============================================================
CREATE TABLE IF NOT EXISTS public.web_search_cache (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  query_hash TEXT UNIQUE NOT NULL, -- MD5 de la requête
  query_text TEXT NOT NULL,
  results JSONB NOT NULL, -- Résultats de recherche
  language TEXT DEFAULT 'fr',
  expires_at TIMESTAMPTZ NOT NULL, -- Cache valide 24h
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_search_cache_query_hash ON public.web_search_cache(query_hash);
CREATE INDEX IF NOT EXISTS idx_search_cache_expires_at ON public.web_search_cache(expires_at);

-- ============================================================
-- TABLE : notifications (historique push)
-- ============================================================
CREATE TABLE IF NOT EXISTS public.notifications (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES public.users(id) ON DELETE CASCADE NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  data JSONB, -- Données supplémentaires pour deep linking
  sent_at TIMESTAMPTZ DEFAULT NOW(),
  read_at TIMESTAMPTZ,
  fcm_message_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON public.notifications(user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_sent_at ON public.notifications(sent_at DESC);

-- ============================================================
-- TABLE : developer_context (Données développeur pour l'IA)
-- ============================================================
CREATE TABLE IF NOT EXISTS public.developer_context (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  key TEXT UNIQUE NOT NULL,
  content TEXT NOT NULL,
  embedding vector(1024), -- Si on veut faire du RAG sur le contexte dev
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Données développeur (upsert : ré-exécution sans doublon de clé)
INSERT INTO public.developer_context (key, content) VALUES
('developer_name', 'Faycal Habib Ahmat'),
('developer_title', 'Full-Stack AI Engineer & Mobile Developer'),
('developer_bio', 'Expert en développement Flutter, Python FastAPI, et intégration d''APIs d''intelligence artificielle. Spécialisé dans les solutions IA pour le Tchad et l''Afrique francophone. Basé à N''Djamena, Tchad. Passionné par la création d''applications mobiles innovantes utilisant les dernières technologies LLM (Large Language Models) comme GPT, Claude, Llama, et Gemini.'),
('developer_skills', 'Flutter, Dart, Python, FastAPI, Supabase, Firebase, PostgreSQL, Redis, Docker, Git, REST APIs, Groq, OpenAI, Google Gemini, Mistral AI, Pinecone, Cloudflare, Render.com, Machine Learning, NLP, RAG (Retrieval-Augmented Generation), Mobile Development (iOS/Android), Web Development'),
('developer_languages', 'Français (natif), Arabe (courant), Anglais (professionnel)'),
('developer_email', 'faycalhabibahmat@gmail.com'),
('developer_github', 'https://github.com/faycalhabibahmatahmat'),
('developer_linkedin', 'https://www.linkedin.com/in/faycal-habib'),
('developer_location', 'N''Djamena, Tchad, Afrique Centrale'),
('developer_timezone', 'UTC+1 (Africa/Ndjamena)'),
('project_name', 'SAYIBI AI'),
('project_description', 'SAYIBI AI est une application mobile d''assistance IA multilingue développée par Faycal Habib Ahmat. L''app permet de discuter avec des modèles IA avancés, d''analyser des documents, de générer des fichiers professionnels (CV, lettres, rapports), et d''effectuer des recherches web intelligentes. Conçue pour l''Afrique francophone avec support du français, de l''arabe, et de l''anglais.'),
('project_vision', 'Démocratiser l''accès à l''intelligence artificielle au Tchad et en Afrique en créant des outils gratuits, performants et adaptés aux contextes locaux (connectivité limitée, multilinguisme, besoins spécifiques).'),
('project_tech_stack', 'Frontend: Flutter avec Material 3, Riverpod, Dio, Hive. Backend: Python FastAPI, Supabase PostgreSQL, Upstash Redis, Cloudflare R2. IA: Groq (Llama 3.3), Google Gemini (chaîne de modèles), Mistral AI. Services: Tavily (recherche web), ElevenLabs (TTS), Pinecone (vecteurs). Hébergement: Render.com. Notifications: Firebase Cloud Messaging.'),
('company_name', 'SAYIBI Technologies'),
('company_mission', 'Fournir des solutions d''intelligence artificielle accessibles et performantes pour transformer la productivité en Afrique.')
ON CONFLICT (key) DO UPDATE SET
  content = EXCLUDED.content,
  updated_at = NOW();

DROP TRIGGER IF EXISTS developer_context_updated_at ON public.developer_context;
CREATE TRIGGER developer_context_updated_at BEFORE UPDATE ON public.developer_context
FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- ROW LEVEL SECURITY (RLS)
-- ============================================================

-- Activer RLS sur toutes les tables
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.generated_files ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.usage_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.web_search_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.developer_context ENABLE ROW LEVEL SECURITY;

-- POLICIES : users
DROP POLICY IF EXISTS "Users can view own profile" ON public.users;
DROP POLICY IF EXISTS "Users can update own profile" ON public.users;
CREATE POLICY "Users can view own profile"
  ON public.users FOR SELECT
  USING (auth.uid() = id);

CREATE POLICY "Users can update own profile"
  ON public.users FOR UPDATE
  USING (auth.uid() = id);

-- POLICIES : chat_sessions
DROP POLICY IF EXISTS "Users can view own sessions" ON public.chat_sessions;
DROP POLICY IF EXISTS "Users can create own sessions" ON public.chat_sessions;
DROP POLICY IF EXISTS "Users can update own sessions" ON public.chat_sessions;
DROP POLICY IF EXISTS "Users can delete own sessions" ON public.chat_sessions;
CREATE POLICY "Users can view own sessions"
  ON public.chat_sessions FOR SELECT
  USING (auth.uid() = user_id);

CREATE POLICY "Users can create own sessions"
  ON public.chat_sessions FOR INSERT
  WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own sessions"
  ON public.chat_sessions FOR UPDATE
  USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own sessions"
  ON public.chat_sessions FOR DELETE
  USING (auth.uid() = user_id);

-- POLICIES : messages
DROP POLICY IF EXISTS "Users can view messages from own sessions" ON public.messages;
DROP POLICY IF EXISTS "Users can insert messages to own sessions" ON public.messages;
CREATE POLICY "Users can view messages from own sessions"
  ON public.messages FOR SELECT
  USING (
    EXISTS (
      SELECT 1 FROM public.chat_sessions
      WHERE id = session_id AND user_id = auth.uid()
    )
  );

CREATE POLICY "Users can insert messages to own sessions"
  ON public.messages FOR INSERT
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM public.chat_sessions
      WHERE id = session_id AND user_id = auth.uid()
    )
  );

-- POLICIES : documents
DROP POLICY IF EXISTS "Users can view own documents" ON public.documents;
DROP POLICY IF EXISTS "Users can insert own documents" ON public.documents;
DROP POLICY IF EXISTS "Users can delete own documents" ON public.documents;
CREATE POLICY "Users can view own documents"
  ON public.documents FOR SELECT
  USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own documents"
  ON public.documents FOR INSERT
  WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can delete own documents"
  ON public.documents FOR DELETE
  USING (auth.uid() = user_id);

-- POLICIES : generated_files
DROP POLICY IF EXISTS "Users can view own generated files" ON public.generated_files;
DROP POLICY IF EXISTS "Users can insert own generated files" ON public.generated_files;
DROP POLICY IF EXISTS "Users can delete own generated files" ON public.generated_files;
CREATE POLICY "Users can view own generated files"
  ON public.generated_files FOR SELECT
  USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own generated files"
  ON public.generated_files FOR INSERT
  WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can delete own generated files"
  ON public.generated_files FOR DELETE
  USING (auth.uid() = user_id);

-- POLICIES : usage_logs (lecture seule pour l'utilisateur)
DROP POLICY IF EXISTS "Users can view own usage logs" ON public.usage_logs;
CREATE POLICY "Users can view own usage logs"
  ON public.usage_logs FOR SELECT
  USING (auth.uid() = user_id);

-- POLICIES : notifications
DROP POLICY IF EXISTS "Users can view own notifications" ON public.notifications;
DROP POLICY IF EXISTS "Users can update own notifications" ON public.notifications;
CREATE POLICY "Users can view own notifications"
  ON public.notifications FOR SELECT
  USING (auth.uid() = user_id);

CREATE POLICY "Users can update own notifications"
  ON public.notifications FOR UPDATE
  USING (auth.uid() = user_id);

-- POLICIES : web_search_cache (lecture publique, écriture service_role)
DROP POLICY IF EXISTS "Anyone can read search cache" ON public.web_search_cache;
CREATE POLICY "Anyone can read search cache"
  ON public.web_search_cache FOR SELECT
  USING (true);

-- POLICIES : developer_context (lecture publique pour l'IA)
DROP POLICY IF EXISTS "Anyone can read developer context" ON public.developer_context;
CREATE POLICY "Anyone can read developer context"
  ON public.developer_context FOR SELECT
  USING (true);

-- ============================================================
-- STORAGE BUCKETS RLS
-- ============================================================

INSERT INTO storage.buckets (id, name, public) VALUES ('user-avatars', 'user-avatars', true)
ON CONFLICT (id) DO NOTHING;
INSERT INTO storage.buckets (id, name, public) VALUES ('uploaded-documents', 'uploaded-documents', false)
ON CONFLICT (id) DO NOTHING;
INSERT INTO storage.buckets (id, name, public) VALUES ('generated-files', 'generated-files', false)
ON CONFLICT (id) DO NOTHING;

DROP POLICY IF EXISTS "Avatar images are publicly accessible" ON storage.objects;
DROP POLICY IF EXISTS "Users can upload own avatar" ON storage.objects;
DROP POLICY IF EXISTS "Users can update own avatar" ON storage.objects;
DROP POLICY IF EXISTS "Users can view own documents" ON storage.objects;
DROP POLICY IF EXISTS "Users can upload documents" ON storage.objects;
DROP POLICY IF EXISTS "Users can delete own documents" ON storage.objects;
DROP POLICY IF EXISTS "Users can view own generated files" ON storage.objects;
DROP POLICY IF EXISTS "Users can upload generated files" ON storage.objects;
DROP POLICY IF EXISTS "Users can delete own generated files" ON storage.objects;

CREATE POLICY "Avatar images are publicly accessible"
  ON storage.objects FOR SELECT
  USING (bucket_id = 'user-avatars');

CREATE POLICY "Users can upload own avatar"
  ON storage.objects FOR INSERT
  WITH CHECK (bucket_id = 'user-avatars' AND auth.uid()::text = (storage.foldername(name))[1]);

CREATE POLICY "Users can update own avatar"
  ON storage.objects FOR UPDATE
  USING (bucket_id = 'user-avatars' AND auth.uid()::text = (storage.foldername(name))[1]);

CREATE POLICY "Users can view own documents"
  ON storage.objects FOR SELECT
  USING (bucket_id = 'uploaded-documents' AND auth.uid()::text = (storage.foldername(name))[1]);

CREATE POLICY "Users can upload documents"
  ON storage.objects FOR INSERT
  WITH CHECK (bucket_id = 'uploaded-documents' AND auth.uid()::text = (storage.foldername(name))[1]);

CREATE POLICY "Users can delete own documents"
  ON storage.objects FOR DELETE
  USING (bucket_id = 'uploaded-documents' AND auth.uid()::text = (storage.foldername(name))[1]);

CREATE POLICY "Users can view own generated files"
  ON storage.objects FOR SELECT
  USING (bucket_id = 'generated-files' AND auth.uid()::text = (storage.foldername(name))[1]);

CREATE POLICY "Users can upload generated files"
  ON storage.objects FOR INSERT
  WITH CHECK (bucket_id = 'generated-files' AND auth.uid()::text = (storage.foldername(name))[1]);

CREATE POLICY "Users can delete own generated files"
  ON storage.objects FOR DELETE
  USING (bucket_id = 'generated-files' AND auth.uid()::text = (storage.foldername(name))[1]);

-- ============================================================
-- FONCTIONS UTILITAIRES
-- ============================================================

-- Fonction pour mettre à jour total_tokens_used dans users
CREATE OR REPLACE FUNCTION update_user_tokens()
RETURNS TRIGGER AS $$
BEGIN
  UPDATE public.users
  SET total_tokens_used = total_tokens_used + NEW.tokens_used
  WHERE id = NEW.user_id;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS usage_logs_update_tokens ON public.usage_logs;
CREATE TRIGGER usage_logs_update_tokens AFTER INSERT ON public.usage_logs
FOR EACH ROW EXECUTE FUNCTION update_user_tokens();

-- Profil public.users après inscription (email, Google, Apple, etc.)
-- Métadonnées courantes : full_name, name, given_name+family_name, avatar_url, picture (Google), photo_url
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
DECLARE
  meta JSONB := COALESCE(NEW.raw_user_meta_data, '{}'::jsonb);
  v_email TEXT := COALESCE(NEW.email, '');
  v_full TEXT;
  v_avatar TEXT;
  v_lang TEXT;
  v_theme TEXT;
BEGIN
  v_full := COALESCE(
    NULLIF(trim(meta->>'full_name'), ''),
    NULLIF(trim(meta->>'name'), ''),
    NULLIF(trim(concat_ws(' ',
      NULLIF(trim(meta->>'given_name'), ''),
      NULLIF(trim(meta->>'family_name'), '')
    )), ''),
    NULLIF(split_part(v_email, '@', 1), '')
  );

  v_avatar := COALESCE(
    NULLIF(trim(meta->>'avatar_url'), ''),
    NULLIF(trim(meta->>'picture'), ''),
    NULLIF(trim(meta->>'photo_url'), '')
  );

  v_lang := COALESCE(NULLIF(trim(meta->>'language'), ''), 'fr');
  IF v_lang NOT IN ('fr', 'ar', 'en') THEN
    v_lang := 'fr';
  END IF;

  v_theme := COALESCE(NULLIF(trim(meta->>'theme'), ''), 'dark');
  IF v_theme NOT IN ('light', 'dark') THEN
    v_theme := 'dark';
  END IF;

  INSERT INTO public.users (
    id, email, full_name, avatar_url,
    language, plan, model_preference, theme
  )
  VALUES (
    NEW.id,
    v_email,
    v_full,
    v_avatar,
    v_lang,
    'free',
    'auto',
    v_theme
  )
  ON CONFLICT (id) DO UPDATE SET
    email = EXCLUDED.email,
    full_name = COALESCE(public.users.full_name, EXCLUDED.full_name),
    avatar_url = COALESCE(public.users.avatar_url, EXCLUDED.avatar_url),
    updated_at = NOW();

  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- ============================================================
-- EDGE FUNCTIONS (optionnel — logique métier côté Supabase)
-- ============================================================

-- Exemple : fonction pour nettoyer le cache expiré
CREATE OR REPLACE FUNCTION clean_expired_cache()
RETURNS void AS $$
BEGIN
  DELETE FROM public.web_search_cache WHERE expires_at < NOW();
END;
$$ LANGUAGE plpgsql;

-- À exécuter via pg_cron ou Edge Function périodique
