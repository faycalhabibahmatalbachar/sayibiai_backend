-- =============================================================================
-- Migration 010 — Module CRM / User Intelligence (admin)
-- Tables: tags, notes internes, profils ML cache, webhooks sortants, segments.
-- Index pg_trgm pour recherche tolérante. Vue v_admin_users_full + country_code.
-- Exécuter dans Supabase SQL Editor (service_role utilisé par l’API admin).
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Recherche floue (nécessite ANALYZE users après gros imports)
CREATE INDEX IF NOT EXISTS idx_users_email_trgm
  ON public.users USING gin (email gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_users_full_name_trgm
  ON public.users USING gin (COALESCE(full_name, '') gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_users_plan_status_helper
  ON public.users (plan, created_at DESC);

-- Tags appliqués par l’équipe admin
CREATE TABLE IF NOT EXISTS public.admin_user_tags (
  user_id   UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  tag       TEXT NOT NULL,
  tagged_by UUID REFERENCES public.admin_users(id) ON DELETE SET NULL,
  tagged_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (user_id, tag)
);
CREATE INDEX IF NOT EXISTS idx_admin_user_tags_tag ON public.admin_user_tags (tag);
CREATE INDEX IF NOT EXISTS idx_admin_user_tags_user ON public.admin_user_tags (user_id);

-- Notes internes (markdown)
CREATE TABLE IF NOT EXISTS public.admin_user_notes (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  admin_id   UUID NOT NULL REFERENCES public.admin_users(id) ON DELETE CASCADE,
  content    TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_admin_user_notes_user ON public.admin_user_notes (user_id, created_at DESC);

-- Cache scores ML / heuristiques (recalcul côté API)
CREATE TABLE IF NOT EXISTS public.user_ml_profiles (
  user_id              UUID PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
  engagement_score     INT,
  churn_risk           INT,
  upsell_propensity    INT,
  ltv_estimate_cents   BIGINT,
  health_label         TEXT,
  model_version        TEXT DEFAULT 'heuristic_v1',
  calculated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Webhooks HTTPS pour intégrations tierces (événements user.*)
CREATE TABLE IF NOT EXISTS public.admin_webhooks (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  url        TEXT NOT NULL,
  events     TEXT[] NOT NULL DEFAULT '{}',
  secret     TEXT,
  is_active  BOOLEAN NOT NULL DEFAULT true,
  created_by UUID REFERENCES public.admin_users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_admin_webhooks_active ON public.admin_webhooks (is_active);

-- Segments sauvegardés (filtres JSON)
CREATE TABLE IF NOT EXISTS public.admin_saved_segments (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name        TEXT NOT NULL,
  description TEXT,
  filters     JSONB NOT NULL DEFAULT '{}',
  created_by  UUID REFERENCES public.admin_users(id) ON DELETE SET NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.admin_user_tags      DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.admin_user_notes     DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_ml_profiles     DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.admin_webhooks       DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.admin_saved_segments DISABLE ROW LEVEL SECURITY;

GRANT ALL ON public.admin_user_tags      TO service_role;
GRANT ALL ON public.admin_user_notes     TO service_role;
GRANT ALL ON public.user_ml_profiles     TO service_role;
GRANT ALL ON public.admin_webhooks       TO service_role;
GRANT ALL ON public.admin_saved_segments TO service_role;

-- Vue enrichie : ajout country_code (migration 009)
CREATE OR REPLACE VIEW public.v_admin_users_full AS
SELECT
  u.id,
  u.email,
  u.full_name,
  u.avatar_url,
  u.language,
  u.country_code,
  u.plan,
  u.model_preference,
  u.total_tokens_used,
  u.created_at,
  u.updated_at,
  (u.fcm_token IS NOT NULL)                                                       AS has_fcm,
  (SELECT MAX(ul.created_at) FROM public.usage_logs ul WHERE ul.user_id = u.id)   AS last_seen_at,
  (SELECT COUNT(*) FROM public.chat_sessions cs WHERE cs.user_id = u.id)          AS total_sessions,
  (SELECT COUNT(*) FROM public.messages msg
     JOIN public.chat_sessions cs ON cs.id = msg.session_id
     WHERE cs.user_id = u.id)                                                      AS total_messages,
  (SELECT COUNT(*) FROM public.documents d WHERE d.user_id = u.id)                AS total_documents,
  (SELECT COUNT(*) FROM public.generated_files gf WHERE gf.user_id = u.id)        AS total_generated_files,
  (SELECT COUNT(*) FROM public.usage_logs ul
     WHERE ul.user_id = u.id AND ul.created_at >= CURRENT_DATE)                   AS requests_today,
  (SELECT COUNT(*) FROM public.usage_logs ul
     WHERE ul.user_id = u.id
       AND ul.created_at >= DATE_TRUNC('month', NOW()))                            AS requests_month,
  (SELECT COUNT(*) FROM public.moderation_queue mq
     WHERE mq.user_id = u.id AND mq.status IN ('rejected','banned'))              AS flag_count,
  LEAST(100,
    COALESCE(
      (SELECT COUNT(*) FROM public.moderation_queue mq
         WHERE mq.user_id = u.id AND mq.status = 'rejected'), 0
    ) * 15
    + CASE WHEN u.total_tokens_used > 1000000 THEN 10 ELSE 0 END
    + CASE WHEN (
        SELECT COUNT(*) FROM public.usage_logs ul
         WHERE ul.user_id = u.id
           AND ul.status_code >= 400
           AND ul.created_at >= NOW() - INTERVAL '7 days'
      ) > 20 THEN 15 ELSE 0 END
  )::INT                                                                           AS risk_score,
  CASE
    WHEN EXISTS (
      SELECT 1 FROM public.moderation_queue mq
        WHERE mq.user_id = u.id AND mq.status = 'banned'
    ) THEN 'banned'
    WHEN (SELECT MAX(ul.created_at) FROM public.usage_logs ul WHERE ul.user_id = u.id)
         >= NOW() - INTERVAL '30 days' THEN 'active'
    WHEN u.created_at >= NOW() - INTERVAL '7 days'  THEN 'active'
    ELSE 'inactive'
  END                                                                              AS status,
  (SELECT COUNT(*) FROM public.notifications n WHERE n.user_id = u.id)            AS notifications_count,
  COALESCE(
    (SELECT COUNT(*) FROM public.inbound_calls ic WHERE ic.user_id = u.id), 0
  )                                                                                AS voice_calls,
  COALESCE(
    (SELECT COUNT(*) FROM public.sms_log sl WHERE sl.user_id = u.id), 0
  )                                                                                AS sms_count,
  COALESCE(
    (SELECT COUNT(*) FROM public.generated_images gi WHERE gi.user_id = u.id), 0
  )                                                                                AS total_generated_images
FROM public.users u;

COMMENT ON VIEW public.v_admin_users_full IS 'Vue enrichie users + country_code + compteur images générées';
