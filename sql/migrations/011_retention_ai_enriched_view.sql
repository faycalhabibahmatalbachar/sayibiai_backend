-- =============================================================================
-- Migration 011 — RGPD / IA admin + vue enrichie (idempotent, ordre libre)
--
-- Crée si besoin : user_ml_profiles, generated_images (stub minimal), tables NL.
-- Puis : engagement_series, admin_settings, v_admin_users_full (JOIN ML).
-- Ensuite : 012_seed_engagement_series_from_usage.sql
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ─── Comptages optionnels (tables absentes → 0, pas d’erreur 42P01) ───
CREATE OR REPLACE FUNCTION public._admin_count_user_rows(p_table TEXT, p_user_id UUID)
RETURNS BIGINT
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  r BIGINT;
BEGIN
  IF to_regclass('public.' || p_table) IS NULL THEN
    RETURN 0;
  END IF;
  EXECUTE format('SELECT COUNT(*)::bigint FROM public.%I WHERE user_id = $1', p_table) INTO r USING p_user_id;
  RETURN COALESCE(r, 0);
END;
$$;
COMMENT ON FUNCTION public._admin_count_user_rows IS
  'Compte les lignes par user_id si la table existe (generated_images, inbound_calls, sms_log, …).';

-- Table CRM / ML (identique à 010 ; ici pour exécution sans 010)
CREATE TABLE IF NOT EXISTS public.user_ml_profiles (
  user_id              UUID PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
  engagement_score     INT,
  churn_risk           INT,
  upsell_propensity    INT,
  ltv_estimate_cents   BIGINT,
  health_label         TEXT,
  model_version        TEXT DEFAULT 'heuristic_v1',
  calculated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  engagement_series    JSONB
);

ALTER TABLE public.user_ml_profiles
  ADD COLUMN IF NOT EXISTS engagement_series JSONB;

COMMENT ON COLUMN public.user_ml_profiles.engagement_series IS
  'JSON array : 7 entiers, requêtes usage_logs par jour (voir 012).';

ALTER TABLE public.user_ml_profiles DISABLE ROW LEVEL SECURITY;
GRANT ALL ON public.user_ml_profiles TO service_role;

-- Index recherche (si pas déjà créés par 010)
CREATE INDEX IF NOT EXISTS idx_users_email_trgm
  ON public.users USING gin (email gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_users_full_name_trgm
  ON public.users USING gin (COALESCE(full_name, '') gin_trgm_ops);

-- Tags / notes CRM (référencés par l’API admin)
CREATE TABLE IF NOT EXISTS public.admin_user_tags (
  user_id   UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  tag       TEXT NOT NULL,
  tagged_by UUID REFERENCES public.admin_users(id) ON DELETE SET NULL,
  tagged_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (user_id, tag)
);
CREATE TABLE IF NOT EXISTS public.admin_user_notes (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  admin_id   UUID NOT NULL REFERENCES public.admin_users(id) ON DELETE CASCADE,
  content    TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE public.admin_user_tags DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.admin_user_notes DISABLE ROW LEVEL SECURITY;
GRANT ALL ON public.admin_user_tags TO service_role;
GRANT ALL ON public.admin_user_notes TO service_role;

-- État archivage / anonymisation
CREATE TABLE IF NOT EXISTS public.user_gdpr_retention (
  user_id            UUID PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
  archived_at        TIMESTAMPTZ,
  archive_reason     TEXT,
  anonymized_at      TIMESTAMPTZ,
  anonymization_note TEXT,
  purge_after_at     TIMESTAMPTZ,
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_gdpr_retention_purge
  ON public.user_gdpr_retention (purge_after_at)
  WHERE purge_after_at IS NOT NULL AND anonymized_at IS NULL;

-- Journal recherche NL
CREATE TABLE IF NOT EXISTS public.admin_nl_search_log (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  admin_id        UUID REFERENCES public.admin_users(id) ON DELETE SET NULL,
  query_text      TEXT NOT NULL,
  parsed_filters  JSONB,
  result_count    INT,
  latency_ms      INT,
  model_version   TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_admin_nl_search_created ON public.admin_nl_search_log (created_at DESC);

-- Insights
CREATE TABLE IF NOT EXISTS public.admin_user_insight_events (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  kind        TEXT NOT NULL,
  severity    TEXT NOT NULL DEFAULT 'info' CHECK (severity IN ('info','warning','critical')),
  payload     JSONB NOT NULL DEFAULT '{}',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_admin_insight_user ON public.admin_user_insight_events (user_id, created_at DESC);

INSERT INTO public.admin_settings AS s (key, value, description) VALUES
  ('data_retention_policy', jsonb_build_object(
    'raw_usage_logs_days', 365,
    'archive_inactive_after_days', 180,
    'anonymize_after_archive_days', 30,
    'scheduled_purge_cron', '0 3 * * 0',
    'gdpr_auto_anonymize_enabled', false,
    'notes', 'Ajuster selon DPA ; jobs : anonymiser PII, puis purge user_gdpr_retention.purge_after_at'
  ), 'Politique conservation / archivage / anonymisation RGPD'),
  ('ai_admin_features', jsonb_build_object(
    'nl_search_enabled', true,
    'insight_detection_enabled', false,
    'assistant_enabled', true,
    'model_endpoint', null
  ), 'Flags fonctionnalités IA admin (recherche NL, insights, assistant)')
ON CONFLICT (key) DO UPDATE
  SET value = COALESCE(s.value, '{}'::jsonb) || COALESCE(EXCLUDED.value, '{}'::jsonb),
      description = EXCLUDED.description,
      updated_at = NOW();

-- Vue admin (même logique que 010 + colonnes ML)
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
  public._admin_count_user_rows('inbound_calls', u.id)                             AS voice_calls,
  public._admin_count_user_rows('sms_log', u.id)                                   AS sms_count,
  public._admin_count_user_rows('generated_images', u.id)                          AS total_generated_images,
  m.engagement_score,
  m.churn_risk,
  m.upsell_propensity,
  m.health_label,
  m.model_version    AS ml_model_version,
  m.calculated_at    AS ml_calculated_at,
  m.engagement_series
FROM public.users u
LEFT JOIN public.user_ml_profiles m ON m.user_id = u.id;

COMMENT ON VIEW public.v_admin_users_full IS
  'Vue enrichie users + ML + engagement_series.';

ALTER TABLE public.user_gdpr_retention     DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.admin_nl_search_log     DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.admin_user_insight_events DISABLE ROW LEVEL SECURITY;

GRANT ALL ON public.user_gdpr_retention TO service_role;
GRANT ALL ON public.admin_nl_search_log TO service_role;
GRANT ALL ON public.admin_user_insight_events TO service_role;
GRANT SELECT ON public.v_admin_users_full TO service_role;
GRANT SELECT ON public.v_admin_users_full TO anon;

GRANT EXECUTE ON FUNCTION public._admin_count_user_rows(TEXT, UUID) TO service_role;
GRANT EXECUTE ON FUNCTION public._admin_count_user_rows(TEXT, UUID) TO anon;
