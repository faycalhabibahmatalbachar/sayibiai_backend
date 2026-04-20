-- SMS/Contacts exploitation + Alarmes CRUD (idempotent)

CREATE TABLE IF NOT EXISTS public.contact_identities (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES public.users(id) ON DELETE CASCADE NOT NULL,
  source_contact_id TEXT NOT NULL,
  display_name TEXT,
  normalized_name TEXT,
  phones JSONB DEFAULT '[]'::jsonb,
  last_seen_at TIMESTAMPTZ DEFAULT NOW(),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (user_id, source_contact_id)
);

CREATE INDEX IF NOT EXISTS idx_contact_identities_user_name
  ON public.contact_identities (user_id, normalized_name);

DROP TRIGGER IF EXISTS contact_identities_updated_at ON public.contact_identities;
CREATE TRIGGER contact_identities_updated_at
  BEFORE UPDATE ON public.contact_identities
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TABLE IF NOT EXISTS public.contact_aliases (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES public.users(id) ON DELETE CASCADE NOT NULL,
  contact_identity_id UUID REFERENCES public.contact_identities(id) ON DELETE CASCADE NOT NULL,
  alias TEXT NOT NULL,
  confidence REAL DEFAULT 0.8,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_contact_aliases_user_alias
  ON public.contact_aliases (user_id, alias);

CREATE TABLE IF NOT EXISTS public.sms_action_queue (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES public.users(id) ON DELETE CASCADE NOT NULL,
  contact_identity_id UUID REFERENCES public.contact_identities(id) ON DELETE SET NULL,
  to_e164 TEXT NOT NULL,
  body TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'confirmed', 'sent', 'failed', 'cancelled')),
  origin TEXT DEFAULT 'agent',
  provider TEXT DEFAULT 'device',
  request_id TEXT,
  client_meta JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  sent_at TIMESTAMPTZ,
  error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_sms_action_queue_user_created
  ON public.sms_action_queue (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_sms_action_queue_status_created
  ON public.sms_action_queue (status, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sms_action_queue_user_request_id
  ON public.sms_action_queue (user_id, request_id)
  WHERE request_id IS NOT NULL;

DROP TRIGGER IF EXISTS sms_action_queue_updated_at ON public.sms_action_queue;
CREATE TRIGGER sms_action_queue_updated_at
  BEFORE UPDATE ON public.sms_action_queue
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TABLE IF NOT EXISTS public.alarms (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES public.users(id) ON DELETE CASCADE NOT NULL,
  title TEXT NOT NULL,
  message TEXT,
  scheduled_for TIMESTAMPTZ NOT NULL,
  timezone TEXT NOT NULL DEFAULT 'Africa/Ndjamena',
  repeat_rule TEXT,
  is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
  status TEXT NOT NULL DEFAULT 'scheduled'
    CHECK (status IN ('scheduled', 'triggered', 'dismissed', 'cancelled', 'failed')),
  delivery_channel TEXT NOT NULL DEFAULT 'push'
    CHECK (delivery_channel IN ('push', 'in_app', 'device_alarm')),
  last_triggered_at TIMESTAMPTZ,
  next_trigger_at TIMESTAMPTZ,
  metadata JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alarms_user_scheduled
  ON public.alarms (user_id, scheduled_for DESC);

CREATE INDEX IF NOT EXISTS idx_alarms_due
  ON public.alarms (is_enabled, next_trigger_at);

DROP TRIGGER IF EXISTS alarms_updated_at ON public.alarms;
CREATE TRIGGER alarms_updated_at
  BEFORE UPDATE ON public.alarms
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TABLE IF NOT EXISTS public.alarm_events (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  alarm_id UUID REFERENCES public.alarms(id) ON DELETE CASCADE NOT NULL,
  user_id UUID REFERENCES public.users(id) ON DELETE CASCADE NOT NULL,
  event_type TEXT NOT NULL,
  payload JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alarm_events_alarm_created
  ON public.alarm_events (alarm_id, created_at DESC);
