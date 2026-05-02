-- =============================================================================
-- Migration 009 — Analytics : fenêtre étendue, agrégations paramétrées, funnel SQL
-- =============================================================================

-- 1) Colonne optionnelle pour la répartition géographique (ISO 3166-1 alpha-2)
ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS country_code CHAR(2);

COMMENT ON COLUMN public.users.country_code IS 'Code pays ISO 3166-1 alpha-2 (ex. FR, US), renseigné par l’app ou l’admin';

CREATE INDEX IF NOT EXISTS idx_users_country_code
  ON public.users (country_code)
  WHERE country_code IS NOT NULL;

-- 2) Vue journalière : fenêtre élargie (~400 jours, jours UTC)
--    Note : CREATE OR REPLACE ne peut pas changer le type d’une colonne → DROP puis CREATE.
DROP VIEW IF EXISTS public.v_daily_stats CASCADE;

CREATE VIEW public.v_daily_stats AS
SELECT
  DATE(ul.created_at AT TIME ZONE 'UTC')                                       AS date,
  COUNT(*)::BIGINT                                                             AS total_requests,
  COUNT(DISTINCT ul.user_id)::BIGINT                                           AS active_users,
  COALESCE(SUM(ul.tokens_used), 0)::BIGINT                                     AS total_tokens,
  COALESCE(AVG(ul.request_duration_ms), 0)                                     AS avg_latency_ms,
  COUNT(*) FILTER (WHERE ul.status_code >= 400)::BIGINT                         AS error_count,
  COUNT(*) FILTER (WHERE ul.status_code >= 500)::BIGINT                        AS server_errors,
  COUNT(*) FILTER (WHERE ul.status_code = 200)::BIGINT                         AS success_count
FROM public.usage_logs ul
WHERE ul.created_at >= (NOW() AT TIME ZONE 'UTC') - INTERVAL '400 days'
GROUP BY DATE(ul.created_at AT TIME ZONE 'UTC')
ORDER BY date DESC;

COMMENT ON VIEW public.v_daily_stats IS 'Statistiques journalières (usage_logs), jusqu’à ~400 jours — UTC par jour';

GRANT SELECT ON public.v_daily_stats TO service_role;
GRANT SELECT ON public.v_daily_stats TO anon;

-- 3) Série journalière paramétrée (1–366 jours) pour /admin/analytics/daily
--    Recréation si le type de retour a déjà été publié autrement.
DROP FUNCTION IF EXISTS public.fn_daily_stats(INT);

CREATE FUNCTION public.fn_daily_stats(p_days INT DEFAULT 30)
RETURNS TABLE(
  date DATE,
  total_requests BIGINT,
  active_users BIGINT,
  total_tokens BIGINT,
  avg_latency_ms NUMERIC,
  error_count BIGINT,
  server_errors BIGINT,
  success_count BIGINT
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  d INT := LEAST(GREATEST(COALESCE(p_days, 30), 1), 366);
BEGIN
  RETURN QUERY
  SELECT
    DATE(ul.created_at AT TIME ZONE 'UTC')                                       AS d,
    COUNT(*)::BIGINT,
    COUNT(DISTINCT ul.user_id)::BIGINT,
    COALESCE(SUM(ul.tokens_used), 0)::BIGINT,
    COALESCE(AVG(ul.request_duration_ms), 0),
    COUNT(*) FILTER (WHERE ul.status_code >= 400)::BIGINT,
    COUNT(*) FILTER (WHERE ul.status_code >= 500)::BIGINT,
    COUNT(*) FILTER (WHERE ul.status_code = 200)::BIGINT
  FROM public.usage_logs ul
  WHERE ul.created_at >= (NOW() AT TIME ZONE 'UTC') - (d || ' days')::INTERVAL
  GROUP BY DATE(ul.created_at AT TIME ZONE 'UTC')
  ORDER BY d DESC;
END;
$$;

COMMENT ON FUNCTION public.fn_daily_stats(INT) IS 'Agrégats journaliers usage_logs sur une fenêtre glissante (p_days, max 366), fuseau UTC';

-- 4) Funnel cohérent : utilisateurs distincts (plus de comptage brut sessions / messages)
CREATE OR REPLACE FUNCTION public.fn_analytics_funnel(p_days INT DEFAULT 30)
RETURNS JSONB
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  d         INT := LEAST(GREATEST(COALESCE(p_days, 30), 1), 366);
  since_ts  TIMESTAMPTZ := (NOW() AT TIME ZONE 'UTC') - (d || ' days')::INTERVAL;
  v_total   BIGINT;
  v_new     BIGINT;
  v_sess    BIGINT;
  v_msg     BIGINT;
  v_paid    BIGINT;
  c_new     NUMERIC;
  c_sess    NUMERIC;
  c_msg     NUMERIC;
  c_paid    NUMERIC;
BEGIN
  SELECT COUNT(*) INTO v_total FROM public.users;

  SELECT COUNT(*) INTO v_new
  FROM public.users
  WHERE created_at >= since_ts;

  -- Inscrits dans la période ayant créé au moins une session (dans la période)
  SELECT COUNT(DISTINCT u.id) INTO v_sess
  FROM public.users u
  INNER JOIN public.chat_sessions cs ON cs.user_id = u.id AND cs.created_at >= since_ts
  WHERE u.created_at >= since_ts;

  -- Inscrits dans la période ayant envoyé au moins un message utilisateur (dans la période)
  SELECT COUNT(DISTINCT u.id) INTO v_msg
  FROM public.users u
  INNER JOIN public.chat_sessions cs ON cs.user_id = u.id
  INNER JOIN public.messages m ON m.session_id = cs.id AND m.created_at >= since_ts AND m.role = 'user'
  WHERE u.created_at >= since_ts;

  SELECT COUNT(*) INTO v_paid
  FROM public.users
  WHERE plan IS NOT NULL AND LOWER(plan::TEXT) <> 'free';

  c_new  := ROUND(v_new::NUMERIC  * 100.0 / NULLIF(v_total, 0), 2);
  c_sess := ROUND(v_sess::NUMERIC * 100.0 / NULLIF(v_new, 0), 2);
  c_msg  := ROUND(v_msg::NUMERIC  * 100.0 / NULLIF(v_sess, 0), 2);
  c_paid := ROUND(v_paid::NUMERIC * 100.0 / NULLIF(v_total, 0), 2);

  RETURN jsonb_build_object(
    'period_days', d,
    'stages', jsonb_build_array(
      jsonb_build_object('stage', 'Total Users', 'users', v_total, 'conversion', 100.0),
      jsonb_build_object('stage', 'New Signups', 'users', v_new, 'conversion', COALESCE(c_new, 0)),
      jsonb_build_object('stage', 'New → Session', 'users', v_sess, 'conversion', COALESCE(c_sess, 0)),
      jsonb_build_object('stage', 'New → Message', 'users', v_msg, 'conversion', COALESCE(c_msg, 0)),
      jsonb_build_object('stage', 'Paid Plan', 'users', v_paid, 'conversion', COALESCE(c_paid, 0))
    )
  );
END;
$$;

COMMENT ON FUNCTION public.fn_analytics_funnel(INT) IS 'Funnel conversion : signups récents, adoption session/message, plans payants (tous utilisateurs)';

-- 5) Vue modèles : fenêtre 90 jours (cohérent avec tendances admin)
CREATE OR REPLACE VIEW public.v_model_stats AS
SELECT
  COALESCE(ul.model_used, 'unknown')                                                  AS model_id,
  COUNT(*)                                                                            AS total_requests,
  COUNT(DISTINCT ul.user_id)                                                          AS unique_users,
  COALESCE(AVG(ul.request_duration_ms), 0)::INT                                      AS avg_latency_ms,
  COALESCE(
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ul.request_duration_ms), 0
  )::INT                                                                              AS p50_latency_ms,
  COALESCE(
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY ul.request_duration_ms), 0
  )::INT                                                                              AS p95_latency_ms,
  COALESCE(
    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY ul.request_duration_ms), 0
  )::INT                                                                              AS p99_latency_ms,
  COALESCE(SUM(ul.tokens_used), 0)                                                   AS total_tokens,
  COALESCE(AVG(ul.tokens_used), 0)::INT                                              AS avg_tokens_per_request,
  COUNT(*) FILTER (WHERE ul.status_code >= 400)                                      AS error_count,
  ROUND(
    COUNT(*) FILTER (WHERE ul.status_code >= 400)::NUMERIC
    / NULLIF(COUNT(*), 0) * 100, 2
  )                                                                                   AS error_rate_pct,
  COUNT(*) FILTER (WHERE ul.created_at >= CURRENT_DATE)                              AS requests_today,
  COUNT(*) FILTER (WHERE ul.created_at >= DATE_TRUNC('week', NOW()))                 AS requests_week
FROM public.usage_logs ul
WHERE ul.created_at >= NOW() - INTERVAL '90 days'
GROUP BY COALESCE(ul.model_used, 'unknown')
ORDER BY total_requests DESC;

COMMENT ON VIEW public.v_model_stats IS 'Performance et volume par modèle IA (90 jours glissants)';

-- 7) Rétro-remplissage pays (profils sans country_code) — heuristique langue, à affiner côté produit
UPDATE public.users
SET country_code = CASE LOWER(COALESCE(language, 'fr'))
  WHEN 'fr' THEN 'FR'
  WHEN 'en' THEN 'US'
  WHEN 'ar' THEN 'MA'
  ELSE 'FR'
END::CHAR(2)
WHERE country_code IS NULL;

-- 8) Permissions
GRANT EXECUTE ON FUNCTION public.fn_daily_stats(INT)      TO service_role;
GRANT EXECUTE ON FUNCTION public.fn_analytics_funnel(INT) TO service_role;

DO $$
BEGIN
  RAISE NOTICE '✅ Migration 009 — fn_daily_stats, fn_analytics_funnel, v_daily_stats ~400j, country_code, v_model_stats 90j';
END;
$$;
