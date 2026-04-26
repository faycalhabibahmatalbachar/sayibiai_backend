-- ============================================================
-- MIGRATION 007 — ChadGPT Admin Console Tables
-- Admin authentication, audit logs, moderation queue,
-- analytics views, and dashboard aggregation functions.
-- Idempotent : re-exécutable sans erreur.
-- Exécuter dans Supabase SQL Editor.
-- ============================================================

-- ============================================================
-- TABLE : admin_users — comptes du panneau d'administration
-- ============================================================
CREATE TABLE IF NOT EXISTS public.admin_users (
  id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  email         TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,           -- bcrypt hash
  full_name     TEXT,
  role          TEXT DEFAULT 'moderator' CHECK (role IN (
                  'super_admin','admin','moderator','analyst','support','auditor')),
  permissions   TEXT[] DEFAULT '{}',     -- granular permissions list
  is_active     BOOLEAN DEFAULT true,
  two_fa_enabled BOOLEAN DEFAULT false,
  last_login_at TIMESTAMPTZ,
  last_login_ip TEXT,
  created_at    TIMESTAMPTZ DEFAULT NOW(),
  updated_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_admin_users_email ON public.admin_users(email);

DROP TRIGGER IF EXISTS admin_users_updated_at ON public.admin_users;
CREATE TRIGGER admin_users_updated_at
  BEFORE UPDATE ON public.admin_users
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Seed: super admin account (password = 'admin123' — change in production!)
-- Hash generated with bcrypt rounds=12
INSERT INTO public.admin_users (email, password_hash, full_name, role, permissions)
VALUES (
  'admin@chadgpt.ai',
  '$2b$12$g6sp0UWzFIU2QbYX/gfiD.b3TamljFufBBXdiw3b9OtRy5Li7Txlq',
  'Super Admin',
  'super_admin',
  ARRAY['*']
)
ON CONFLICT (email) DO NOTHING;

-- ============================================================
-- TABLE : admin_audit_log — journal immuable de toutes les actions admin
-- ============================================================
CREATE TABLE IF NOT EXISTS public.admin_audit_log (
  id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  admin_id    UUID REFERENCES public.admin_users(id) ON DELETE SET NULL,
  admin_email TEXT NOT NULL,
  action      TEXT NOT NULL,        -- ban_user, refund, deploy_prompt, etc.
  entity_type TEXT,                 -- user, transaction, model, prompt, etc.
  entity_id   TEXT,
  changes     JSONB,                -- {before: ..., after: ...}
  ip_address  TEXT,
  user_agent  TEXT,
  result      TEXT DEFAULT 'success' CHECK (result IN ('success','failure')),
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_log_admin_id ON public.admin_audit_log(admin_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON public.admin_audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON public.admin_audit_log(entity_type, entity_id);

-- ============================================================
-- TABLE : moderation_queue — file de modération de contenu
-- ============================================================
CREATE TABLE IF NOT EXISTS public.moderation_queue (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id         UUID REFERENCES public.users(id) ON DELETE CASCADE,
  session_id      UUID REFERENCES public.chat_sessions(id) ON DELETE SET NULL,
  message_id      UUID REFERENCES public.messages(id) ON DELETE SET NULL,
  content_type    TEXT DEFAULT 'text' CHECK (content_type IN ('text','image','voice','video')),
  content_preview TEXT,             -- First 500 chars of content
  content_url     TEXT,             -- URL if media
  ai_scores       JSONB NOT NULL DEFAULT '{}',  -- {violence:0, sexual:0, hate:0, self_harm:0, spam:0}
  ai_confidence   REAL DEFAULT 0,
  ai_reasoning    TEXT,
  priority        INT DEFAULT 50,   -- 0-100, higher = review first
  status          TEXT DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected','warned','banned','escalated')),
  reviewed_by     UUID REFERENCES public.admin_users(id) ON DELETE SET NULL,
  decision_reason TEXT,
  flagged_at      TIMESTAMPTZ DEFAULT NOW(),
  reviewed_at     TIMESTAMPTZ,
  auto_action     BOOLEAN DEFAULT false  -- true if AI auto-decided
);

CREATE INDEX IF NOT EXISTS idx_moderation_status ON public.moderation_queue(status);
CREATE INDEX IF NOT EXISTS idx_moderation_priority ON public.moderation_queue(priority DESC, flagged_at ASC);
CREATE INDEX IF NOT EXISTS idx_moderation_user_id ON public.moderation_queue(user_id);
CREATE INDEX IF NOT EXISTS idx_moderation_flagged_at ON public.moderation_queue(flagged_at DESC);

-- ============================================================
-- TABLE : admin_settings — configuration platform
-- ============================================================
CREATE TABLE IF NOT EXISTS public.admin_settings (
  key         TEXT PRIMARY KEY,
  value       JSONB NOT NULL,
  description TEXT,
  updated_by  UUID REFERENCES public.admin_users(id),
  updated_at  TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO public.admin_settings (key, value, description) VALUES
  ('maintenance_mode', 'false', 'Disable user access for maintenance'),
  ('rate_limit_per_hour', '1000', 'API calls per user per hour'),
  ('moderation_auto_threshold', '{"sexual": 90, "violence": 85, "hate": 80, "self_harm": 70}', 'Auto-reject thresholds'),
  ('allowed_plans', '["free","pro","enterprise"]', 'Available subscription plans'),
  ('free_requests_per_day', '50', 'Daily request limit for free users'),
  ('pro_requests_per_day', '1000', 'Daily request limit for pro users')
ON CONFLICT (key) DO NOTHING;

-- ============================================================
-- VIEW : v_admin_users_full — vue enrichie des utilisateurs
-- Utilisée par GET /admin/users
-- ============================================================
CREATE OR REPLACE VIEW public.v_admin_users_full AS
SELECT
  u.id,
  u.email,
  u.full_name,
  u.avatar_url,
  u.language,
  u.plan,
  u.model_preference,
  u.total_tokens_used,
  u.fcm_token IS NOT NULL AS has_fcm,
  u.created_at,
  u.updated_at,
  -- Last activity from usage_logs
  (SELECT MAX(ul.created_at) FROM public.usage_logs ul WHERE ul.user_id = u.id) AS last_seen_at,
  -- Session count
  (SELECT COUNT(*) FROM public.chat_sessions cs WHERE cs.user_id = u.id) AS total_sessions,
  -- Message count
  (SELECT COUNT(*) FROM public.messages m
   JOIN public.chat_sessions cs ON cs.id = m.session_id
   WHERE cs.user_id = u.id) AS total_messages,
  -- Document count
  (SELECT COUNT(*) FROM public.documents d WHERE d.user_id = u.id) AS total_documents,
  -- Generated files count
  (SELECT COUNT(*) FROM public.generated_files gf WHERE gf.user_id = u.id) AS total_generated_files,
  -- Requests today
  (SELECT COUNT(*) FROM public.usage_logs ul
   WHERE ul.user_id = u.id AND ul.created_at >= CURRENT_DATE) AS requests_today,
  -- Requests this month
  (SELECT COUNT(*) FROM public.usage_logs ul
   WHERE ul.user_id = u.id AND ul.created_at >= DATE_TRUNC('month', NOW())) AS requests_month,
  -- Moderation flags
  (SELECT COUNT(*) FROM public.moderation_queue mq
   WHERE mq.user_id = u.id AND mq.status IN ('rejected','banned')) AS flag_count,
  -- Risk score (simple heuristic: high flags + high token usage + recent)
  LEAST(100, (
    COALESCE((SELECT COUNT(*) FROM public.moderation_queue mq WHERE mq.user_id = u.id AND mq.status = 'rejected'), 0) * 15 +
    CASE WHEN u.total_tokens_used > 1000000 THEN 10 ELSE 0 END +
    CASE WHEN (SELECT COUNT(*) FROM public.usage_logs ul WHERE ul.user_id = u.id AND ul.status_code >= 400 AND ul.created_at >= NOW() - INTERVAL '7 days') > 20 THEN 15 ELSE 0 END
  ))::INT AS risk_score,
  -- Status (active if used in last 30 days)
  CASE
    WHEN EXISTS (SELECT 1 FROM public.moderation_queue mq WHERE mq.user_id = u.id AND mq.status = 'banned') THEN 'banned'
    WHEN (SELECT MAX(ul.created_at) FROM public.usage_logs ul WHERE ul.user_id = u.id) >= NOW() - INTERVAL '30 days' THEN 'active'
    WHEN u.created_at >= NOW() - INTERVAL '7 days' THEN 'active'
    ELSE 'inactive'
  END AS status,
  -- Notification count
  (SELECT COUNT(*) FROM public.notifications n WHERE n.user_id = u.id) AS notifications_count,
  -- Voice calls (inbound_calls table)
  COALESCE((SELECT COUNT(*) FROM public.inbound_calls ic WHERE ic.user_id = u.id), 0) AS voice_calls,
  -- SMS count
  COALESCE((SELECT COUNT(*) FROM public.sms_log sl WHERE sl.user_id = u.id), 0) AS sms_count
FROM public.users u;

-- ============================================================
-- VIEW : v_daily_stats — statistiques journalières (30 derniers jours)
-- ============================================================
CREATE OR REPLACE VIEW public.v_daily_stats AS
SELECT
  DATE(ul.created_at) AS date,
  COUNT(*) AS total_requests,
  COUNT(DISTINCT ul.user_id) AS active_users,
  SUM(ul.tokens_used) AS total_tokens,
  AVG(ul.request_duration_ms) AS avg_latency_ms,
  COUNT(*) FILTER (WHERE ul.status_code >= 400) AS error_count,
  COUNT(*) FILTER (WHERE ul.status_code >= 500) AS server_errors,
  COUNT(*) FILTER (WHERE ul.status_code = 200) AS success_count
FROM public.usage_logs ul
WHERE ul.created_at >= NOW() - INTERVAL '30 days'
GROUP BY DATE(ul.created_at)
ORDER BY date DESC;

-- ============================================================
-- VIEW : v_model_stats — statistiques par modèle IA
-- ============================================================
CREATE OR REPLACE VIEW public.v_model_stats AS
SELECT
  COALESCE(ul.model_used, 'unknown') AS model_id,
  COUNT(*) AS total_requests,
  COUNT(DISTINCT ul.user_id) AS unique_users,
  AVG(ul.request_duration_ms)::INT AS avg_latency_ms,
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ul.request_duration_ms)::INT AS p50_latency_ms,
  PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY ul.request_duration_ms)::INT AS p95_latency_ms,
  PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY ul.request_duration_ms)::INT AS p99_latency_ms,
  SUM(ul.tokens_used) AS total_tokens,
  AVG(ul.tokens_used)::INT AS avg_tokens_per_request,
  COUNT(*) FILTER (WHERE ul.status_code >= 400) AS error_count,
  ROUND(
    COUNT(*) FILTER (WHERE ul.status_code >= 400)::NUMERIC / NULLIF(COUNT(*), 0) * 100, 2
  ) AS error_rate_pct,
  -- Today
  COUNT(*) FILTER (WHERE ul.created_at >= CURRENT_DATE) AS requests_today,
  -- This week
  COUNT(*) FILTER (WHERE ul.created_at >= DATE_TRUNC('week', NOW())) AS requests_week
FROM public.usage_logs ul
WHERE ul.created_at >= NOW() - INTERVAL '30 days'
GROUP BY COALESCE(ul.model_used, 'unknown')
ORDER BY total_requests DESC;

-- ============================================================
-- VIEW : v_endpoint_stats — performance par endpoint API
-- ============================================================
CREATE OR REPLACE VIEW public.v_endpoint_stats AS
SELECT
  ul.endpoint,
  COUNT(*) AS total_calls,
  AVG(ul.request_duration_ms)::INT AS avg_latency_ms,
  PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY ul.request_duration_ms)::INT AS p95_latency_ms,
  MAX(ul.request_duration_ms) AS max_latency_ms,
  COUNT(*) FILTER (WHERE ul.status_code >= 400) AS errors,
  ROUND(
    COUNT(*) FILTER (WHERE ul.status_code >= 400)::NUMERIC / NULLIF(COUNT(*), 0) * 100, 2
  ) AS error_rate_pct,
  COUNT(*) FILTER (WHERE ul.created_at >= CURRENT_DATE) AS calls_today
FROM public.usage_logs ul
WHERE ul.created_at >= NOW() - INTERVAL '7 days'
GROUP BY ul.endpoint
ORDER BY total_calls DESC;

-- ============================================================
-- VIEW : v_plan_distribution — répartition des plans
-- ============================================================
CREATE OR REPLACE VIEW public.v_plan_distribution AS
SELECT
  plan,
  COUNT(*) AS user_count,
  ROUND(COUNT(*)::NUMERIC / SUM(COUNT(*)) OVER () * 100, 2) AS percentage,
  COUNT(*) FILTER (WHERE created_at >= DATE_TRUNC('month', NOW())) AS new_this_month,
  COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days') AS new_this_week
FROM public.users
GROUP BY plan
ORDER BY user_count DESC;

-- ============================================================
-- FUNCTION : fn_dashboard_kpis() — KPIs du dashboard en un seul appel
-- ============================================================
CREATE OR REPLACE FUNCTION public.fn_dashboard_kpis()
RETURNS JSONB AS $$
DECLARE
  result JSONB;
  total_users INT;
  active_users_today INT;
  active_users_month INT;
  new_users_today INT;
  new_users_month INT;
  total_requests_today BIGINT;
  total_requests_month BIGINT;
  total_tokens_month BIGINT;
  avg_latency_today INT;
  error_rate_today NUMERIC;
  moderation_pending INT;
  moderation_today INT;
BEGIN
  SELECT COUNT(*) INTO total_users FROM public.users;

  SELECT COUNT(DISTINCT user_id) INTO active_users_today
  FROM public.usage_logs WHERE created_at >= CURRENT_DATE;

  SELECT COUNT(DISTINCT user_id) INTO active_users_month
  FROM public.usage_logs WHERE created_at >= DATE_TRUNC('month', NOW());

  SELECT COUNT(*) INTO new_users_today
  FROM public.users WHERE created_at >= CURRENT_DATE;

  SELECT COUNT(*) INTO new_users_month
  FROM public.users WHERE created_at >= DATE_TRUNC('month', NOW());

  SELECT COUNT(*), SUM(tokens_used), AVG(request_duration_ms)::INT,
    ROUND(COUNT(*) FILTER (WHERE status_code >= 400)::NUMERIC / NULLIF(COUNT(*), 0) * 100, 2)
  INTO total_requests_today, total_tokens_month, avg_latency_today, error_rate_today
  FROM public.usage_logs WHERE created_at >= CURRENT_DATE;

  SELECT COUNT(*) INTO total_requests_month
  FROM public.usage_logs WHERE created_at >= DATE_TRUNC('month', NOW());

  SELECT COUNT(*) INTO moderation_pending
  FROM public.moderation_queue WHERE status = 'pending';

  SELECT COUNT(*) INTO moderation_today
  FROM public.moderation_queue WHERE flagged_at >= CURRENT_DATE;

  result := jsonb_build_object(
    'total_users', COALESCE(total_users, 0),
    'active_users_today', COALESCE(active_users_today, 0),
    'active_users_month', COALESCE(active_users_month, 0),
    'new_users_today', COALESCE(new_users_today, 0),
    'new_users_month', COALESCE(new_users_month, 0),
    'total_requests_today', COALESCE(total_requests_today, 0),
    'total_requests_month', COALESCE(total_requests_month, 0),
    'total_tokens_month', COALESCE(total_tokens_month, 0),
    'avg_latency_ms_today', COALESCE(avg_latency_today, 0),
    'error_rate_today_pct', COALESCE(error_rate_today, 0),
    'moderation_pending', COALESCE(moderation_pending, 0),
    'moderation_today', COALESCE(moderation_today, 0),
    'plans', (SELECT jsonb_agg(row_to_json(p)) FROM (
      SELECT plan, COUNT(*) as count
      FROM public.users GROUP BY plan
    ) p),
    'users_by_language', (SELECT jsonb_agg(row_to_json(l)) FROM (
      SELECT language, COUNT(*) as count
      FROM public.users GROUP BY language
    ) l)
  );

  RETURN result;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ============================================================
-- FUNCTION : fn_user_cohort_retention(months INT) — rétention cohorte
-- ============================================================
CREATE OR REPLACE FUNCTION public.fn_user_cohort_retention(p_months INT DEFAULT 6)
RETURNS TABLE(
  cohort_month TEXT,
  cohort_size BIGINT,
  m0 NUMERIC, m1 NUMERIC, m2 NUMERIC, m3 NUMERIC, m6 NUMERIC, m12 NUMERIC
) AS $$
BEGIN
  RETURN QUERY
  WITH cohorts AS (
    SELECT
      user_id,
      DATE_TRUNC('month', MIN(created_at)) AS cohort_start
    FROM public.usage_logs
    GROUP BY user_id
  ),
  cohort_sizes AS (
    SELECT cohort_start, COUNT(DISTINCT user_id) AS size
    FROM cohorts GROUP BY cohort_start
  ),
  activity AS (
    SELECT
      c.cohort_start,
      DATE_TRUNC('month', ul.created_at) AS activity_month,
      COUNT(DISTINCT ul.user_id) AS active_users
    FROM public.usage_logs ul
    JOIN cohorts c ON c.user_id = ul.user_id
    WHERE ul.created_at >= NOW() - INTERVAL '14 months'
    GROUP BY c.cohort_start, DATE_TRUNC('month', ul.created_at)
  )
  SELECT
    TO_CHAR(cs.cohort_start, 'Mon YYYY') AS cohort_month,
    cs.size AS cohort_size,
    -- M0: same month as cohort (should be ~100%)
    ROUND(COALESCE(
      (SELECT active_users FROM activity a WHERE a.cohort_start = cs.cohort_start
       AND a.activity_month = cs.cohort_start)::NUMERIC / NULLIF(cs.size, 0) * 100, 0), 1) AS m0,
    ROUND(COALESCE(
      (SELECT active_users FROM activity a WHERE a.cohort_start = cs.cohort_start
       AND a.activity_month = cs.cohort_start + INTERVAL '1 month')::NUMERIC / NULLIF(cs.size, 0) * 100, 0), 1) AS m1,
    ROUND(COALESCE(
      (SELECT active_users FROM activity a WHERE a.cohort_start = cs.cohort_start
       AND a.activity_month = cs.cohort_start + INTERVAL '2 months')::NUMERIC / NULLIF(cs.size, 0) * 100, 0), 1) AS m2,
    ROUND(COALESCE(
      (SELECT active_users FROM activity a WHERE a.cohort_start = cs.cohort_start
       AND a.activity_month = cs.cohort_start + INTERVAL '3 months')::NUMERIC / NULLIF(cs.size, 0) * 100, 0), 1) AS m3,
    ROUND(COALESCE(
      (SELECT active_users FROM activity a WHERE a.cohort_start = cs.cohort_start
       AND a.activity_month = cs.cohort_start + INTERVAL '6 months')::NUMERIC / NULLIF(cs.size, 0) * 100, 0), 1) AS m6,
    ROUND(COALESCE(
      (SELECT active_users FROM activity a WHERE a.cohort_start = cs.cohort_start
       AND a.activity_month = cs.cohort_start + INTERVAL '12 months')::NUMERIC / NULLIF(cs.size, 0) * 100, 0), 1) AS m12
  FROM cohort_sizes cs
  WHERE cs.cohort_start >= NOW() - INTERVAL '13 months'
  ORDER BY cs.cohort_start DESC
  LIMIT p_months;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ============================================================
-- Add sample moderation items using existing messages if any
-- (non-destructive — only if moderation_queue is empty)
-- ============================================================
INSERT INTO public.moderation_queue (user_id, content_type, content_preview, ai_scores, ai_confidence, priority)
SELECT
  m.session_id::UUID,  -- placeholder, will be corrected
  'text',
  LEFT(m.content, 300),
  '{"violence": 5, "sexual": 12, "hate": 3, "self_harm": 2, "spam": 8}'::JSONB,
  72,
  35
FROM public.messages m
WHERE m.role = 'user'
  AND LENGTH(m.content) > 50
  AND NOT EXISTS (SELECT 1 FROM public.moderation_queue)
LIMIT 10;

-- Fix: properly set user_id from session
UPDATE public.moderation_queue mq
SET user_id = cs.user_id
FROM public.messages m
JOIN public.chat_sessions cs ON cs.id = m.session_id
WHERE mq.content_preview = LEFT(m.content, 300)
  AND mq.user_id IS NULL;

-- ============================================================
-- RLS : admin tables are service-role only (no user RLS needed)
-- The admin API uses the service_role key, bypassing RLS.
-- Disable RLS on admin tables for simplicity.
-- ============================================================
ALTER TABLE public.admin_users DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.admin_audit_log DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.moderation_queue DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.admin_settings DISABLE ROW LEVEL SECURITY;

-- ============================================================
-- Grant SELECT on views to service role (already has full access,
-- but explicit grants prevent surprises with Supabase Studio).
-- ============================================================
GRANT SELECT ON public.v_admin_users_full TO service_role;
GRANT SELECT ON public.v_daily_stats TO service_role;
GRANT SELECT ON public.v_model_stats TO service_role;
GRANT SELECT ON public.v_endpoint_stats TO service_role;
GRANT SELECT ON public.v_plan_distribution TO service_role;
GRANT EXECUTE ON FUNCTION public.fn_dashboard_kpis() TO service_role;
GRANT EXECUTE ON FUNCTION public.fn_user_cohort_retention(INT) TO service_role;

-- Also allow anon (Supabase Studio preview)
GRANT SELECT ON public.v_admin_users_full TO anon;
GRANT SELECT ON public.v_daily_stats TO anon;
GRANT SELECT ON public.v_model_stats TO anon;
GRANT SELECT ON public.v_plan_distribution TO anon;

COMMENT ON TABLE public.admin_users IS 'ChadGPT Admin Console — comptes administrateurs';
COMMENT ON TABLE public.admin_audit_log IS 'Journal immuable des actions admin — JAMAIS supprimer';
COMMENT ON TABLE public.moderation_queue IS 'File de modération de contenu généré par les utilisateurs';
COMMENT ON TABLE public.admin_settings IS 'Configuration dynamique de la plateforme';
