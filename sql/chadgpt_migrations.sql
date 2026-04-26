-- ============================================================
-- ChadGPT — Migrations SQL complètes
-- Supabase / PostgreSQL avec extension pgvector
-- ============================================================

-- Extension vectorielle pour les embeddings
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- TABLES UTILISATEURS
-- ============================================================

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email TEXT UNIQUE NOT NULL,
    display_name TEXT,
    avatar_url TEXT,
    phone_number TEXT,
    subscription_tier TEXT DEFAULT 'free' CHECK (subscription_tier IN ('free', 'pro', 'enterprise')),
    credits_remaining INTEGER DEFAULT 100,
    preferences JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    device_id TEXT,
    device_type TEXT,
    push_token TEXT,
    last_seen TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_contacts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    contact_name TEXT NOT NULL,
    phone_numbers TEXT[],
    emails TEXT[],
    photo_url TEXT,
    sync_source TEXT DEFAULT 'phone',
    last_synced TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- TABLES CHAT ET MÉMOIRE
-- ============================================================

-- Table conversations (alias chat_sessions pour compatibilité)
CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    title TEXT,
    context_summary TEXT,
    embedding vector(1536),
    is_archived BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS memory_snippets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    embedding vector(1536),
    source_message_id UUID,
    importance_score FLOAT DEFAULT 0.5,
    last_accessed TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- TABLES MÉDIAS GÉNÉRÉS
-- ============================================================

CREATE TABLE IF NOT EXISTS generated_images (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    session_id UUID,
    original_prompt TEXT,
    optimized_prompt TEXT,
    revised_prompt TEXT,
    image_url TEXT,
    watermarked_url TEXT,
    style TEXT DEFAULT 'realistic',
    quality_level TEXT DEFAULT 'standard',
    content_filter_passed BOOLEAN DEFAULT TRUE,
    moderation_flags JSONB DEFAULT '[]',
    generation_cost DECIMAL(10,6) DEFAULT 0,
    parent_image_id UUID REFERENCES generated_images(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS image_edit_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    image_id UUID REFERENCES generated_images(id) ON DELETE CASCADE,
    edit_prompt TEXT,
    edited_url TEXT,
    edit_type TEXT,
    mask_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS generated_videos (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    original_prompt TEXT,
    optimized_prompt TEXT,
    duration_seconds INTEGER DEFAULT 5,
    video_url TEXT,
    watermarked_url TEXT,
    provider TEXT DEFAULT 'runway',
    job_id TEXT,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'queued_no_provider')),
    generation_cost DECIMAL(10,6) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS video_edits (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    original_video_url TEXT,
    edit_type TEXT,
    edit_params JSONB DEFAULT '{}',
    edited_video_url TEXT,
    processing_cost DECIMAL(10,6) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS video_analyses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    video_url TEXT,
    duration_seconds INTEGER,
    analysis_type TEXT DEFAULT 'full',
    full_analysis JSONB DEFAULT '{}',
    transcript TEXT,
    summary TEXT,
    key_moments JSONB DEFAULT '[]',
    objects_detected JSONB DEFAULT '[]',
    anomalies_detected JSONB DEFAULT '[]',
    processing_cost DECIMAL(10,6) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- TABLES APPELS ET SMS
-- ============================================================

CREATE TABLE IF NOT EXISTS call_settings (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    secretary_enabled BOOLEAN DEFAULT FALSE,
    active_hours JSONB DEFAULT '{"start": "09:00", "end": "18:00"}',
    voice_type TEXT,
    custom_greeting TEXT,
    whitelist_contacts UUID[],
    blacklist_contacts UUID[],
    forward_urgent_calls BOOLEAN DEFAULT TRUE,
    auto_sms_reply BOOLEAN DEFAULT FALSE,
    auto_sms_template TEXT DEFAULT 'Je suis actuellement occupé. Mon assistant IA prendra votre message.',
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS inbound_calls (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    caller_phone TEXT NOT NULL,
    caller_name TEXT,
    caller_contact_id UUID REFERENCES user_contacts(id),
    call_timestamp TIMESTAMPTZ DEFAULT NOW(),
    call_duration_seconds INTEGER DEFAULT 0,
    transcription TEXT,
    summary TEXT,
    sentiment TEXT DEFAULT 'calme',
    urgency_level TEXT DEFAULT 'normal',
    intentions JSONB DEFAULT '{}',
    recording_url TEXT,
    actions_taken JSONB DEFAULT '[]',
    user_read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS outbound_calls (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    recipient_phone TEXT,
    reason TEXT,
    trigger_type TEXT,
    script_used TEXT,
    duration_seconds INTEGER DEFAULT 0,
    outcome TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sms_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    direction TEXT DEFAULT 'inbound' CHECK (direction IN ('inbound', 'outbound')),
    phone_number TEXT NOT NULL,
    body TEXT,
    ai_generated BOOLEAN DEFAULT FALSE,
    read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- TABLES PROACTIVITÉ
-- ============================================================

CREATE TABLE IF NOT EXISTS proactive_calls (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    trigger_type TEXT NOT NULL,
    trigger_data JSONB DEFAULT '{}',
    call_timestamp TIMESTAMPTZ DEFAULT NOW(),
    user_response TEXT,
    actions_taken JSONB DEFAULT '[]',
    outcome TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS proactivity_settings (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    enabled BOOLEAN DEFAULT FALSE,
    urgency_threshold TEXT DEFAULT 'urgent',
    allowed_hours JSONB DEFAULT '{"start": "08:00", "end": "22:00"}',
    enabled_triggers TEXT[] DEFAULT ARRAY['traffic', 'weather', 'calendar_conflict'],
    calendar_connected BOOLEAN DEFAULT FALSE,
    calendar_provider TEXT DEFAULT 'google',
    calendar_access_token TEXT,
    calendar_refresh_token TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS calendar_events_cache (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    external_id TEXT,
    title TEXT,
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ,
    location TEXT,
    participants JSONB DEFAULT '[]',
    provider TEXT DEFAULT 'google',
    last_synced TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, external_id)
);

-- ============================================================
-- TABLES RÉSEAUX SOCIAUX
-- ============================================================

CREATE TABLE IF NOT EXISTS social_accounts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    platform TEXT NOT NULL CHECK (platform IN ('facebook', 'instagram', 'twitter', 'linkedin', 'tiktok')),
    account_username TEXT,
    access_token_encrypted TEXT,
    refresh_token_encrypted TEXT,
    token_expires_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS social_posts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    platforms TEXT[] NOT NULL,
    content TEXT NOT NULL,
    media_urls TEXT[] DEFAULT '{}',
    hashtags TEXT[] DEFAULT '{}',
    scheduled_for TIMESTAMPTZ,
    published_at TIMESTAMPTZ,
    engagement_stats JSONB DEFAULT '{}',
    ai_generated BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS social_interactions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    post_id UUID REFERENCES social_posts(id),
    platform TEXT,
    interaction_type TEXT DEFAULT 'comment',
    author_username TEXT,
    content TEXT,
    ai_response TEXT,
    user_read BOOLEAN DEFAULT FALSE,
    flagged_as_opportunity BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS social_settings (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    auto_publish BOOLEAN DEFAULT FALSE,
    publish_frequency JSONB DEFAULT '{}',
    content_themes TEXT[] DEFAULT '{}',
    tone_of_voice TEXT DEFAULT 'professional',
    auto_reply_comments BOOLEAN DEFAULT FALSE,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- TABLES SURVEILLANCE
-- ============================================================

CREATE TABLE IF NOT EXISTS screen_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    session_start TIMESTAMPTZ DEFAULT NOW(),
    session_end TIMESTAMPTZ,
    frames_analyzed INTEGER DEFAULT 0,
    alerts_triggered INTEGER DEFAULT 0,
    apps_detected JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS screen_alerts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID REFERENCES screen_sessions(id) ON DELETE CASCADE,
    alert_type TEXT,
    app_context TEXT,
    message TEXT,
    suggestion TEXT,
    screenshot_url TEXT,
    user_action TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS video_surveillance_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    camera_source TEXT DEFAULT 'front',
    session_start TIMESTAMPTZ DEFAULT NOW(),
    session_end TIMESTAMPTZ,
    frames_analyzed INTEGER DEFAULT 0,
    alerts_triggered INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS surveillance_alerts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID REFERENCES video_surveillance_sessions(id) ON DELETE CASCADE,
    alert_type TEXT,
    alert_description TEXT,
    frame_snapshot_url TEXT,
    video_clip_url TEXT,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    user_acknowledged BOOLEAN DEFAULT FALSE,
    actions_taken JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS screen_settings (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    enabled BOOLEAN DEFAULT FALSE,
    alert_on_sensitive BOOLEAN DEFAULT TRUE,
    alert_on_errors BOOLEAN DEFAULT TRUE,
    notify_push BOOLEAN DEFAULT TRUE,
    capture_interval_seconds INTEGER DEFAULT 3,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS camera_settings (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    enabled BOOLEAN DEFAULT FALSE,
    alert_on_motion BOOLEAN DEFAULT TRUE,
    alert_on_unknown_person BOOLEAN DEFAULT FALSE,
    notify_push BOOLEAN DEFAULT TRUE,
    record_on_alert BOOLEAN DEFAULT TRUE,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- TABLES AVATARS
-- ============================================================

CREATE TABLE IF NOT EXISTS avatars (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    avatar_name TEXT NOT NULL,
    avatar_type TEXT DEFAULT 'preset' CHECK (avatar_type IN ('preset', 'custom')),
    avatar_provider TEXT DEFAULT 'heygen',
    provider_avatar_id TEXT,
    preview_video_url TEXT,
    voice_id TEXT,
    is_default BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS avatar_conversations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    avatar_id UUID REFERENCES avatars(id),
    message_text TEXT,
    response_text TEXT,
    response_video_url TEXT,
    generation_cost DECIMAL(10,6) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- TABLES FICHIERS INDEXÉS
-- ============================================================

CREATE TABLE IF NOT EXISTS file_index (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    file_name TEXT NOT NULL,
    file_path TEXT,
    file_type TEXT,
    file_size BIGINT DEFAULT 0,
    mime_type TEXT,
    metadata JSONB DEFAULT '{}',
    embedding vector(1536),
    last_modified TIMESTAMPTZ,
    indexed_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- TABLE MODERATION LOGS
-- ============================================================

CREATE TABLE IF NOT EXISTS moderation_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    prompt_hash TEXT NOT NULL,
    flags TEXT[] DEFAULT '{}',
    context TEXT,
    blocked BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- INDEX POUR LES PERFORMANCES
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user ON chat_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_generated_images_user ON generated_images(user_id);
CREATE INDEX IF NOT EXISTS idx_generated_videos_user ON generated_videos(user_id);
CREATE INDEX IF NOT EXISTS idx_generated_videos_job ON generated_videos(job_id);
CREATE INDEX IF NOT EXISTS idx_social_posts_user ON social_posts(user_id);
CREATE INDEX IF NOT EXISTS idx_social_posts_scheduled ON social_posts(scheduled_for) WHERE published_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_social_accounts_user ON social_accounts(user_id);
CREATE INDEX IF NOT EXISTS idx_inbound_calls_user ON inbound_calls(user_id);
CREATE INDEX IF NOT EXISTS idx_screen_alerts_session ON screen_alerts(session_id);
CREATE INDEX IF NOT EXISTS idx_surveillance_alerts_session ON surveillance_alerts(session_id);
CREATE INDEX IF NOT EXISTS idx_file_index_user ON file_index(user_id);
CREATE INDEX IF NOT EXISTS idx_memory_snippets_user ON memory_snippets(user_id);
CREATE INDEX IF NOT EXISTS idx_proactive_calls_user ON proactive_calls(user_id);

-- Index vectoriels pour la recherche sémantique
CREATE INDEX IF NOT EXISTS idx_file_index_embedding ON file_index USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS idx_memory_snippets_embedding ON memory_snippets USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ============================================================
-- ROW LEVEL SECURITY (RLS)
-- ============================================================

ALTER TABLE generated_videos ENABLE ROW LEVEL SECURITY;
CREATE POLICY IF NOT EXISTS "users_own_videos" ON generated_videos FOR ALL USING (auth.uid() = user_id);

ALTER TABLE social_accounts ENABLE ROW LEVEL SECURITY;
CREATE POLICY IF NOT EXISTS "users_own_social_accounts" ON social_accounts FOR ALL USING (auth.uid() = user_id);

ALTER TABLE social_posts ENABLE ROW LEVEL SECURITY;
CREATE POLICY IF NOT EXISTS "users_own_social_posts" ON social_posts FOR ALL USING (auth.uid() = user_id);

ALTER TABLE inbound_calls ENABLE ROW LEVEL SECURITY;
CREATE POLICY IF NOT EXISTS "users_own_calls" ON inbound_calls FOR ALL USING (auth.uid() = user_id);

ALTER TABLE avatars ENABLE ROW LEVEL SECURITY;
CREATE POLICY IF NOT EXISTS "users_own_avatars" ON avatars FOR ALL USING (auth.uid() = user_id);

ALTER TABLE file_index ENABLE ROW LEVEL SECURITY;
CREATE POLICY IF NOT EXISTS "users_own_files" ON file_index FOR ALL USING (auth.uid() = user_id);

ALTER TABLE memory_snippets ENABLE ROW LEVEL SECURITY;
CREATE POLICY IF NOT EXISTS "users_own_memory" ON memory_snippets FOR ALL USING (auth.uid() = user_id);

ALTER TABLE screen_sessions ENABLE ROW LEVEL SECURITY;
CREATE POLICY IF NOT EXISTS "users_own_screen_sessions" ON screen_sessions FOR ALL USING (auth.uid() = user_id);

ALTER TABLE video_surveillance_sessions ENABLE ROW LEVEL SECURITY;
CREATE POLICY IF NOT EXISTS "users_own_surveillance_sessions" ON video_surveillance_sessions FOR ALL USING (auth.uid() = user_id);

-- ============================================================
-- FONCTION DE MISE À JOUR AUTOMATIQUE updated_at
-- ============================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
