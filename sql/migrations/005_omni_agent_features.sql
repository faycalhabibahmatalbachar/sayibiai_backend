-- Omni agent: image generation history, inbound calls, and screen awareness.

CREATE TABLE IF NOT EXISTS public.generated_images (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES public.users(id) ON DELETE CASCADE,
  session_id UUID,
  original_prompt TEXT NOT NULL,
  optimized_prompt TEXT NOT NULL,
  revised_prompt TEXT,
  image_url TEXT NOT NULL,
  watermarked_url TEXT NOT NULL,
  style TEXT,
  quality_level TEXT,
  content_filter_passed BOOLEAN DEFAULT TRUE,
  moderation_flags JSONB,
  generation_cost DECIMAL(10,4) DEFAULT 0,
  parent_image_id UUID REFERENCES public.generated_images(id),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_generated_images_user_created
  ON public.generated_images (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.image_edit_history (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  image_id UUID REFERENCES public.generated_images(id) ON DELETE CASCADE,
  edit_prompt TEXT NOT NULL,
  edited_url TEXT NOT NULL,
  edit_type TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_image_edit_history_image_created
  ON public.image_edit_history (image_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.inbound_calls (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES public.users(id) ON DELETE CASCADE,
  caller_phone TEXT NOT NULL,
  caller_name TEXT,
  caller_contact_id UUID REFERENCES public.contact_identities(id),
  call_timestamp TIMESTAMPTZ NOT NULL,
  call_duration_seconds INT,
  transcription TEXT,
  summary TEXT NOT NULL,
  sentiment TEXT,
  urgency_level TEXT,
  intentions JSONB,
  recording_url TEXT,
  actions_taken JSONB,
  user_read BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_inbound_calls_user_created
  ON public.inbound_calls (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.call_settings (
  user_id UUID PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
  enabled BOOLEAN DEFAULT FALSE,
  active_hours JSONB,
  voice_type TEXT,
  custom_greeting TEXT,
  whitelist_contacts UUID[],
  blacklist_contacts UUID[],
  forward_urgent_calls BOOLEAN DEFAULT TRUE,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.screen_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES public.users(id) ON DELETE CASCADE,
  session_start TIMESTAMPTZ NOT NULL,
  session_end TIMESTAMPTZ,
  frames_analyzed INT DEFAULT 0,
  alerts_triggered INT DEFAULT 0,
  apps_detected JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_screen_sessions_user_created
  ON public.screen_sessions (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.screen_alerts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID REFERENCES public.screen_sessions(id) ON DELETE CASCADE,
  alert_type TEXT NOT NULL,
  app_context TEXT,
  message TEXT NOT NULL,
  suggestion TEXT,
  screenshot_url TEXT,
  user_action TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_screen_alerts_session_created
  ON public.screen_alerts (session_id, created_at DESC);
