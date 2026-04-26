-- ============================================================
-- Migration 006 — Tables Appels, SMS, Secrétariat
-- À exécuter dans Supabase SQL Editor
-- ============================================================

-- call_settings: paramètres du secrétariat vocal par utilisateur
CREATE TABLE IF NOT EXISTS call_settings (
    user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    secretary_enabled BOOLEAN DEFAULT FALSE,
    active_hours JSONB DEFAULT '{"start": "09:00", "end": "18:00"}',
    voice_type TEXT DEFAULT 'female_fr',
    custom_greeting TEXT DEFAULT '',
    whitelist_contacts JSONB DEFAULT '[]',
    blacklist_contacts JSONB DEFAULT '[]',
    forward_urgent_calls BOOLEAN DEFAULT TRUE,
    auto_sms_reply BOOLEAN DEFAULT FALSE,
    auto_sms_template TEXT DEFAULT 'Je suis actuellement occupé. Mon assistant IA prendra votre message.',
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- inbound_calls: historique des appels traités par le secrétariat IA
CREATE TABLE IF NOT EXISTS inbound_calls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    caller_phone TEXT NOT NULL,
    caller_name TEXT,
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

-- sms_log: historique SMS entrants/sortants
CREATE TABLE IF NOT EXISTS sms_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    direction TEXT DEFAULT 'inbound' CHECK (direction IN ('inbound', 'outbound')),
    phone_number TEXT NOT NULL,
    body TEXT,
    ai_generated BOOLEAN DEFAULT FALSE,
    read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- sms_action_queue: file d'envoi de SMS via Flutter natif
CREATE TABLE IF NOT EXISTS sms_action_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    contact_identity_id UUID,
    to_e164 TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT DEFAULT 'draft' CHECK (status IN ('draft', 'pending', 'sent', 'failed', 'cancelled')),
    origin TEXT DEFAULT 'agent',
    provider TEXT DEFAULT 'device',
    request_id TEXT,
    client_meta JSONB DEFAULT '{}',
    sent_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- contact_identities: contacts synchronisés depuis le téléphone
CREATE TABLE IF NOT EXISTS contact_identities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    source_contact_id TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    normalized_name TEXT DEFAULT '',
    phones JSONB DEFAULT '[]',
    last_seen_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, source_contact_id)
);

-- outbound_calls: appels sortants initiés par l'IA
CREATE TABLE IF NOT EXISTS outbound_calls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    recipient_phone TEXT,
    reason TEXT,
    trigger_type TEXT,
    script_used TEXT,
    duration_seconds INTEGER DEFAULT 0,
    outcome TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index performances
CREATE INDEX IF NOT EXISTS idx_inbound_calls_user ON inbound_calls(user_id);
CREATE INDEX IF NOT EXISTS idx_inbound_calls_ts ON inbound_calls(call_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_sms_log_user ON sms_log(user_id);
CREATE INDEX IF NOT EXISTS idx_sms_log_created ON sms_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sms_queue_user ON sms_action_queue(user_id);
CREATE INDEX IF NOT EXISTS idx_sms_queue_status ON sms_action_queue(status);
CREATE INDEX IF NOT EXISTS idx_contact_identities_user ON contact_identities(user_id);
CREATE INDEX IF NOT EXISTS idx_contact_identities_name ON contact_identities(user_id, normalized_name);

-- RLS: chaque utilisateur ne voit que ses données
ALTER TABLE call_settings ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "user_owns_call_settings" ON call_settings;
CREATE POLICY "user_owns_call_settings" ON call_settings
    FOR ALL USING (auth.uid() = user_id);

ALTER TABLE inbound_calls ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "user_owns_inbound_calls" ON inbound_calls;
CREATE POLICY "user_owns_inbound_calls" ON inbound_calls
    FOR ALL USING (auth.uid() = user_id);

ALTER TABLE sms_log ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "user_owns_sms_log" ON sms_log;
CREATE POLICY "user_owns_sms_log" ON sms_log
    FOR ALL USING (auth.uid() = user_id);

ALTER TABLE sms_action_queue ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "user_owns_sms_queue" ON sms_action_queue;
CREATE POLICY "user_owns_sms_queue" ON sms_action_queue
    FOR ALL USING (auth.uid() = user_id);

ALTER TABLE contact_identities ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "user_owns_contacts" ON contact_identities;
CREATE POLICY "user_owns_contacts" ON contact_identities
    FOR ALL USING (auth.uid() = user_id);

-- Trigger updated_at pour call_settings
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS update_call_settings_updated_at ON call_settings;
CREATE TRIGGER update_call_settings_updated_at
    BEFORE UPDATE ON call_settings
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
