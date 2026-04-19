-- Apprentissage des résolutions de contacts + journaux d'actions agent (SAYIBI v2)

CREATE TABLE IF NOT EXISTS public.contact_resolutions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES public.users(id) ON DELETE CASCADE NOT NULL,
  query TEXT NOT NULL,
  contact_id_chosen TEXT NOT NULL,
  display_name_snapshot TEXT,
  resolution_type TEXT DEFAULT 'user_picked',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_contact_resolutions_user_query
  ON public.contact_resolutions (user_id, query);

CREATE TABLE IF NOT EXISTS public.agent_action_logs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES public.users(id) ON DELETE CASCADE NOT NULL,
  action_type TEXT NOT NULL,
  contact_id TEXT,
  phone_masked TEXT,
  message_preview TEXT,
  status TEXT DEFAULT 'success',
  ambiguity_type TEXT,
  confidence REAL,
  client_meta JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_action_logs_user_created
  ON public.agent_action_logs (user_id, created_at DESC);
