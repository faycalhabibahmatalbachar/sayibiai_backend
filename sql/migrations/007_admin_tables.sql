-- ============================================================
-- MIGRATION 007 — ChadGPT Admin Console
-- VERSION CORRIGÉE : supprime les objets existants puis recrée
-- Exécuter dans : Supabase SQL Editor → Run
-- ============================================================

-- ============================================================
-- ÉTAPE 1 : Suppression propre dans l'ordre inverse des dépendances
-- ============================================================

-- Fonctions
DROP FUNCTION IF EXISTS public.fn_dashboard_kpis() CASCADE;
DROP FUNCTION IF EXISTS public.fn_user_cohort_retention(INT) CASCADE;

-- Vues (CASCADE supprime aussi les dépendances éventuelles)
DROP VIEW IF EXISTS public.v_admin_users_full CASCADE;
DROP VIEW IF EXISTS public.v_daily_stats CASCADE;
DROP VIEW IF EXISTS public.v_model_stats CASCADE;
DROP VIEW IF EXISTS public.v_endpoint_stats CASCADE;
DROP VIEW IF EXISTS public.v_plan_distribution CASCADE;

-- Tables admin (ordre : enfants avant parents)
DROP TABLE IF EXISTS public.admin_audit_log CASCADE;
DROP TABLE IF EXISTS public.moderation_queue CASCADE;
DROP TABLE IF EXISTS public.admin_settings CASCADE;
DROP TABLE IF EXISTS public.admin_users CASCADE;

-- ============================================================
-- ÉTAPE 2 : Tables admin
-- ============================================================

-- TABLE : admin_users
CREATE TABLE public.admin_users (
  id             UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
  email          TEXT        UNIQUE NOT NULL,
  password_hash  TEXT        NOT NULL,
  full_name      TEXT,
  role           TEXT        NOT NULL DEFAULT 'moderator'
                             CHECK (role IN ('super_admin','admin','moderator','analyst','support','auditor')),
  permissions    TEXT[]      NOT NULL DEFAULT '{}',
  is_active      BOOLEAN     NOT NULL DEFAULT true,
  two_fa_enabled BOOLEAN     NOT NULL DEFAULT false,
  last_login_at  TIMESTAMPTZ,
  last_login_ip  TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_admin_users_email      ON public.admin_users(email);
CREATE INDEX idx_admin_users_role       ON public.admin_users(role);

CREATE TRIGGER admin_users_updated_at
  BEFORE UPDATE ON public.admin_users
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Compte super-admin par défaut (password = "admin123")
-- Hash bcrypt rounds=12 — changer en production !
INSERT INTO public.admin_users
  (email, password_hash, full_name, role, permissions)
VALUES
  ('admin@chadgpt.ai',
   '$2b$12$g6sp0UWzFIU2QbYX/gfiD.b3TamljFufBBXdiw3b9OtRy5Li7Txlq',
   'Super Admin', 'super_admin', ARRAY['*'])
ON CONFLICT (email) DO UPDATE
  SET password_hash = EXCLUDED.password_hash,
      role          = EXCLUDED.role,
      permissions   = EXCLUDED.permissions,
      updated_at    = NOW();

-- TABLE : admin_audit_log  (journal immuable — ne jamais supprimer des lignes)
CREATE TABLE public.admin_audit_log (
  id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
  admin_id    UUID        REFERENCES public.admin_users(id) ON DELETE SET NULL,
  admin_email TEXT        NOT NULL,
  action      TEXT        NOT NULL,
  entity_type TEXT,
  entity_id   TEXT,
  changes     JSONB       DEFAULT '{}',
  ip_address  TEXT,
  user_agent  TEXT,
  result      TEXT        NOT NULL DEFAULT 'success'
                          CHECK (result IN ('success','failure')),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_admin_id   ON public.admin_audit_log(admin_id);
CREATE INDEX idx_audit_created_at ON public.admin_audit_log(created_at DESC);
CREATE INDEX idx_audit_entity     ON public.admin_audit_log(entity_type, entity_id);
CREATE INDEX idx_audit_action     ON public.admin_audit_log(action);

-- TABLE : moderation_queue
CREATE TABLE public.moderation_queue (
  id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
  -- user_id nullable : certains flags système n'ont pas d'utilisateur associé
  user_id         UUID        REFERENCES public.users(id) ON DELETE CASCADE,
  session_id      UUID        REFERENCES public.chat_sessions(id) ON DELETE SET NULL,
  message_id      UUID        REFERENCES public.messages(id) ON DELETE SET NULL,
  content_type    TEXT        NOT NULL DEFAULT 'text'
                              CHECK (content_type IN ('text','image','voice','video')),
  content_preview TEXT,
  content_url     TEXT,
  ai_scores       JSONB       NOT NULL DEFAULT '{"violence":0,"sexual":0,"hate":0,"self_harm":0,"spam":0}',
  ai_confidence   REAL        NOT NULL DEFAULT 0 CHECK (ai_confidence BETWEEN 0 AND 100),
  ai_reasoning    TEXT,
  priority        INT         NOT NULL DEFAULT 50 CHECK (priority BETWEEN 0 AND 100),
  status          TEXT        NOT NULL DEFAULT 'pending'
                              CHECK (status IN ('pending','approved','rejected','warned','banned','escalated')),
  reviewed_by     UUID        REFERENCES public.admin_users(id) ON DELETE SET NULL,
  decision_reason TEXT,
  flagged_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  reviewed_at     TIMESTAMPTZ,
  auto_action     BOOLEAN     NOT NULL DEFAULT false
);

CREATE INDEX idx_mod_status     ON public.moderation_queue(status);
CREATE INDEX idx_mod_priority   ON public.moderation_queue(priority DESC, flagged_at ASC);
CREATE INDEX idx_mod_user_id    ON public.moderation_queue(user_id);
CREATE INDEX idx_mod_flagged_at ON public.moderation_queue(flagged_at DESC);

-- TABLE : admin_settings
CREATE TABLE public.admin_settings (
  key         TEXT        PRIMARY KEY,
  value       JSONB       NOT NULL,
  description TEXT,
  updated_by  UUID        REFERENCES public.admin_users(id) ON DELETE SET NULL,
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO public.admin_settings (key, value, description) VALUES
  ('maintenance_mode',           'false',                                                          'Désactiver l''accès utilisateurs pour maintenance'),
  ('rate_limit_per_hour',        '1000',                                                           'Nombre max de requêtes API par utilisateur par heure'),
  ('moderation_auto_threshold',  '{"sexual":90,"violence":85,"hate":80,"self_harm":70,"spam":95}', 'Seuils d''auto-rejet (score IA %)'),
  ('allowed_plans',              '["free","pro","enterprise"]',                                    'Plans d''abonnement disponibles'),
  ('free_requests_per_day',      '50',                                                             'Quota journalier — plan Free'),
  ('pro_requests_per_day',       '1000',                                                           'Quota journalier — plan Pro'),
  ('admin_session_hours',        '8',                                                              'Durée de session admin en heures'),
  ('require_2fa_for_admins',     'false',                                                          'Forcer le 2FA pour tous les admins')
ON CONFLICT (key) DO UPDATE
  SET value       = EXCLUDED.value,
      description = EXCLUDED.description,
      updated_at  = NOW();

-- ============================================================
-- ÉTAPE 3 : Désactivation RLS (accès via service_role uniquement)
-- ============================================================
ALTER TABLE public.admin_users      DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.admin_audit_log  DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.moderation_queue DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.admin_settings   DISABLE ROW LEVEL SECURITY;

-- ============================================================
-- ÉTAPE 4 : Données de démonstration — moderation_queue
-- Insère des vrais messages avec les vrais user_id via JOIN.
-- Ne s'exécute que si la table est vide.
-- ============================================================
INSERT INTO public.moderation_queue
  (user_id, session_id, message_id, content_type, content_preview, ai_scores, ai_confidence, priority)
SELECT
  cs.user_id,                        -- vrai user_id depuis chat_sessions
  m.session_id,                      -- session liée
  m.id,                              -- message source
  'text',
  LEFT(m.content, 300),
  jsonb_build_object(
    'violence',  FLOOR(RANDOM() * 20)::INT,
    'sexual',    FLOOR(RANDOM() * 30)::INT,
    'hate',      FLOOR(RANDOM() * 15)::INT,
    'self_harm', FLOOR(RANDOM() * 10)::INT,
    'spam',      FLOOR(RANDOM() * 25)::INT
  ),
  FLOOR(60 + RANDOM() * 40)::REAL,   -- confidence entre 60 et 100
  FLOOR(30 + RANDOM() * 50)::INT     -- priority entre 30 et 80
FROM public.messages m
JOIN public.chat_sessions cs ON cs.id = m.session_id
-- Vérifie que le user existe bien dans public.users (FK safe)
JOIN public.users u ON u.id = cs.user_id
WHERE m.role = 'user'
  AND LENGTH(COALESCE(m.content, '')) > 20
  AND NOT EXISTS (SELECT 1 FROM public.moderation_queue LIMIT 1)
LIMIT 15;

-- ============================================================
-- ÉTAPE 5 : Vues analytiques
-- ============================================================

-- Vue : utilisateurs enrichis (source principale de GET /admin/users)
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
  u.created_at,
  u.updated_at,
  (u.fcm_token IS NOT NULL)                                                       AS has_fcm,
  -- Dernière activité
  (SELECT MAX(ul.created_at) FROM public.usage_logs ul WHERE ul.user_id = u.id)   AS last_seen_at,
  -- Compteurs
  (SELECT COUNT(*) FROM public.chat_sessions cs WHERE cs.user_id = u.id)          AS total_sessions,
  (SELECT COUNT(*) FROM public.messages msg
     JOIN public.chat_sessions cs ON cs.id = msg.session_id
     WHERE cs.user_id = u.id)                                                      AS total_messages,
  (SELECT COUNT(*) FROM public.documents d WHERE d.user_id = u.id)                AS total_documents,
  (SELECT COUNT(*) FROM public.generated_files gf WHERE gf.user_id = u.id)        AS total_generated_files,
  -- Activité récente
  (SELECT COUNT(*) FROM public.usage_logs ul
     WHERE ul.user_id = u.id AND ul.created_at >= CURRENT_DATE)                   AS requests_today,
  (SELECT COUNT(*) FROM public.usage_logs ul
     WHERE ul.user_id = u.id
       AND ul.created_at >= DATE_TRUNC('month', NOW()))                            AS requests_month,
  -- Modération
  (SELECT COUNT(*) FROM public.moderation_queue mq
     WHERE mq.user_id = u.id AND mq.status IN ('rejected','banned'))              AS flag_count,
  -- Score de risque (heuristique simple 0-100)
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
  -- Statut calculé
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
  -- Notifications
  (SELECT COUNT(*) FROM public.notifications n WHERE n.user_id = u.id)            AS notifications_count,
  -- Appels vocaux (table inbound_calls — optionnel)
  COALESCE(
    (SELECT COUNT(*) FROM public.inbound_calls ic WHERE ic.user_id = u.id), 0
  )                                                                                AS voice_calls,
  -- SMS (table sms_log — optionnel)
  COALESCE(
    (SELECT COUNT(*) FROM public.sms_log sl WHERE sl.user_id = u.id), 0
  )                                                                                AS sms_count
FROM public.users u;

-- Vue : statistiques journalières (30 jours)
CREATE OR REPLACE VIEW public.v_daily_stats AS
SELECT
  DATE(ul.created_at)                                                  AS date,
  COUNT(*)                                                             AS total_requests,
  COUNT(DISTINCT ul.user_id)                                           AS active_users,
  COALESCE(SUM(ul.tokens_used), 0)                                     AS total_tokens,
  COALESCE(AVG(ul.request_duration_ms), 0)                             AS avg_latency_ms,
  COUNT(*) FILTER (WHERE ul.status_code >= 400)                        AS error_count,
  COUNT(*) FILTER (WHERE ul.status_code >= 500)                        AS server_errors,
  COUNT(*) FILTER (WHERE ul.status_code = 200)                         AS success_count
FROM public.usage_logs ul
WHERE ul.created_at >= NOW() - INTERVAL '30 days'
GROUP BY DATE(ul.created_at)
ORDER BY date DESC;

-- Vue : statistiques par modèle IA
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
WHERE ul.created_at >= NOW() - INTERVAL '30 days'
GROUP BY COALESCE(ul.model_used, 'unknown')
ORDER BY total_requests DESC;

-- Vue : performance par endpoint
CREATE OR REPLACE VIEW public.v_endpoint_stats AS
SELECT
  ul.endpoint,
  COUNT(*)                                                                            AS total_calls,
  COALESCE(AVG(ul.request_duration_ms), 0)::INT                                      AS avg_latency_ms,
  COALESCE(
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY ul.request_duration_ms), 0
  )::INT                                                                              AS p95_latency_ms,
  COALESCE(MAX(ul.request_duration_ms), 0)                                           AS max_latency_ms,
  COUNT(*) FILTER (WHERE ul.status_code >= 400)                                      AS errors,
  ROUND(
    COUNT(*) FILTER (WHERE ul.status_code >= 400)::NUMERIC
    / NULLIF(COUNT(*), 0) * 100, 2
  )                                                                                   AS error_rate_pct,
  COUNT(*) FILTER (WHERE ul.created_at >= CURRENT_DATE)                              AS calls_today
FROM public.usage_logs ul
WHERE ul.created_at >= NOW() - INTERVAL '7 days'
GROUP BY ul.endpoint
ORDER BY total_calls DESC;

-- Vue : répartition des plans
CREATE OR REPLACE VIEW public.v_plan_distribution AS
SELECT
  plan,
  COUNT(*)                                                                            AS user_count,
  ROUND(COUNT(*)::NUMERIC / NULLIF(SUM(COUNT(*)) OVER (), 0) * 100, 2)              AS percentage,
  COUNT(*) FILTER (WHERE created_at >= DATE_TRUNC('month', NOW()))                   AS new_this_month,
  COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days')                   AS new_this_week
FROM public.users
GROUP BY plan
ORDER BY user_count DESC;

-- ============================================================
-- ÉTAPE 6 : Fonctions analytiques
-- ============================================================

-- Fonction : tous les KPIs du dashboard en un seul appel RPC
CREATE OR REPLACE FUNCTION public.fn_dashboard_kpis()
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_total_users          INT     := 0;
  v_active_today         INT     := 0;
  v_active_month         INT     := 0;
  v_new_today            INT     := 0;
  v_new_month            INT     := 0;
  v_requests_today       BIGINT  := 0;
  v_requests_month       BIGINT  := 0;
  v_tokens_today         BIGINT  := 0;
  v_avg_latency_today    INT     := 0;
  v_error_rate_today     NUMERIC := 0;
  v_mod_pending          INT     := 0;
  v_mod_today            INT     := 0;
BEGIN
  SELECT COUNT(*) INTO v_total_users FROM public.users;

  SELECT COUNT(DISTINCT user_id) INTO v_active_today
  FROM public.usage_logs WHERE created_at >= CURRENT_DATE;

  SELECT COUNT(DISTINCT user_id) INTO v_active_month
  FROM public.usage_logs WHERE created_at >= DATE_TRUNC('month', NOW());

  SELECT COUNT(*) INTO v_new_today  FROM public.users WHERE created_at >= CURRENT_DATE;
  SELECT COUNT(*) INTO v_new_month  FROM public.users WHERE created_at >= DATE_TRUNC('month', NOW());

  SELECT
    COUNT(*),
    COALESCE(SUM(tokens_used), 0),
    COALESCE(AVG(request_duration_ms)::INT, 0),
    ROUND(
      COUNT(*) FILTER (WHERE status_code >= 400)::NUMERIC
      / NULLIF(COUNT(*), 0) * 100, 2
    )
  INTO v_requests_today, v_tokens_today, v_avg_latency_today, v_error_rate_today
  FROM public.usage_logs WHERE created_at >= CURRENT_DATE;

  SELECT COUNT(*) INTO v_requests_month
  FROM public.usage_logs WHERE created_at >= DATE_TRUNC('month', NOW());

  SELECT COUNT(*) INTO v_mod_pending
  FROM public.moderation_queue WHERE status = 'pending';

  SELECT COUNT(*) INTO v_mod_today
  FROM public.moderation_queue WHERE flagged_at >= CURRENT_DATE;

  RETURN jsonb_build_object(
    'total_users',          COALESCE(v_total_users, 0),
    'active_users_today',   COALESCE(v_active_today, 0),
    'active_users_month',   COALESCE(v_active_month, 0),
    'new_users_today',      COALESCE(v_new_today, 0),
    'new_users_month',      COALESCE(v_new_month, 0),
    'total_requests_today', COALESCE(v_requests_today, 0),
    'total_requests_month', COALESCE(v_requests_month, 0),
    'total_tokens_today',   COALESCE(v_tokens_today, 0),
    'avg_latency_ms_today', COALESCE(v_avg_latency_today, 0),
    'error_rate_today_pct', COALESCE(v_error_rate_today, 0),
    'moderation_pending',   COALESCE(v_mod_pending, 0),
    'moderation_today',     COALESCE(v_mod_today, 0),
    'plans', (
      SELECT COALESCE(jsonb_agg(row_to_json(p)), '[]'::JSONB)
      FROM (SELECT plan, COUNT(*) AS count FROM public.users GROUP BY plan) p
    ),
    'users_by_language', (
      SELECT COALESCE(jsonb_agg(row_to_json(l)), '[]'::JSONB)
      FROM (SELECT language, COUNT(*) AS count FROM public.users GROUP BY language) l
    )
  );
END;
$$;

-- Fonction : rétention cohortes mensuelles
CREATE OR REPLACE FUNCTION public.fn_user_cohort_retention(p_months INT DEFAULT 6)
RETURNS TABLE(
  cohort_month TEXT,
  cohort_size  BIGINT,
  m0  NUMERIC,
  m1  NUMERIC,
  m2  NUMERIC,
  m3  NUMERIC,
  m6  NUMERIC,
  m12 NUMERIC
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  RETURN QUERY
  WITH cohorts AS (
    SELECT user_id,
           DATE_TRUNC('month', MIN(created_at)) AS cohort_start
    FROM   public.usage_logs
    GROUP  BY user_id
  ),
  cohort_sizes AS (
    SELECT cohort_start, COUNT(DISTINCT user_id) AS size
    FROM   cohorts
    GROUP  BY cohort_start
  ),
  activity AS (
    SELECT c.cohort_start,
           DATE_TRUNC('month', ul.created_at) AS activity_month,
           COUNT(DISTINCT ul.user_id)          AS active_users
    FROM   public.usage_logs ul
    JOIN   cohorts c ON c.user_id = ul.user_id
    WHERE  ul.created_at >= NOW() - INTERVAL '14 months'
    GROUP  BY c.cohort_start, DATE_TRUNC('month', ul.created_at)
  )
  SELECT
    TO_CHAR(cs.cohort_start, 'Mon YYYY'),
    cs.size,
    ROUND(COALESCE((SELECT active_users FROM activity a WHERE a.cohort_start = cs.cohort_start AND a.activity_month = cs.cohort_start)::NUMERIC                       / NULLIF(cs.size,0)*100, 0), 1),
    ROUND(COALESCE((SELECT active_users FROM activity a WHERE a.cohort_start = cs.cohort_start AND a.activity_month = cs.cohort_start + INTERVAL '1 month')::NUMERIC  / NULLIF(cs.size,0)*100, 0), 1),
    ROUND(COALESCE((SELECT active_users FROM activity a WHERE a.cohort_start = cs.cohort_start AND a.activity_month = cs.cohort_start + INTERVAL '2 months')::NUMERIC / NULLIF(cs.size,0)*100, 0), 1),
    ROUND(COALESCE((SELECT active_users FROM activity a WHERE a.cohort_start = cs.cohort_start AND a.activity_month = cs.cohort_start + INTERVAL '3 months')::NUMERIC / NULLIF(cs.size,0)*100, 0), 1),
    ROUND(COALESCE((SELECT active_users FROM activity a WHERE a.cohort_start = cs.cohort_start AND a.activity_month = cs.cohort_start + INTERVAL '6 months')::NUMERIC / NULLIF(cs.size,0)*100, 0), 1),
    ROUND(COALESCE((SELECT active_users FROM activity a WHERE a.cohort_start = cs.cohort_start AND a.activity_month = cs.cohort_start + INTERVAL '12 months')::NUMERIC/ NULLIF(cs.size,0)*100, 0), 1)
  FROM   cohort_sizes cs
  WHERE  cs.cohort_start >= NOW() - INTERVAL '13 months'
  ORDER  BY cs.cohort_start DESC
  LIMIT  p_months;
END;
$$;

-- ============================================================
-- ÉTAPE 7 : Permissions
-- ============================================================

GRANT SELECT ON public.v_admin_users_full  TO service_role;
GRANT SELECT ON public.v_daily_stats       TO service_role;
GRANT SELECT ON public.v_model_stats       TO service_role;
GRANT SELECT ON public.v_endpoint_stats    TO service_role;
GRANT SELECT ON public.v_plan_distribution TO service_role;
GRANT EXECUTE ON FUNCTION public.fn_dashboard_kpis()               TO service_role;
GRANT EXECUTE ON FUNCTION public.fn_user_cohort_retention(INT)     TO service_role;

-- Accès Supabase Studio (prévisualisation)
GRANT SELECT ON public.v_admin_users_full  TO anon;
GRANT SELECT ON public.v_daily_stats       TO anon;
GRANT SELECT ON public.v_model_stats       TO anon;
GRANT SELECT ON public.v_plan_distribution TO anon;
GRANT EXECUTE ON FUNCTION public.fn_dashboard_kpis()               TO anon;

-- ============================================================
-- ÉTAPE 8 : Commentaires
-- ============================================================
COMMENT ON TABLE public.admin_users      IS 'ChadGPT Admin — comptes administrateurs (accès panneau web)';
COMMENT ON TABLE public.admin_audit_log  IS 'Journal immuable des actions admin — NE JAMAIS SUPPRIMER';
COMMENT ON TABLE public.moderation_queue IS 'File de modération de contenu généré par les utilisateurs';
COMMENT ON TABLE public.admin_settings   IS 'Configuration dynamique de la plateforme (clé/valeur JSONB)';

COMMENT ON VIEW public.v_admin_users_full  IS 'Vue enrichie users : sessions, tokens, flags, risk score, statut';
COMMENT ON VIEW public.v_daily_stats       IS 'Statistiques journalières depuis usage_logs (30 derniers jours)';
COMMENT ON VIEW public.v_model_stats       IS 'Performance et volume par modèle IA (30 jours)';
COMMENT ON VIEW public.v_endpoint_stats    IS 'Latence P95 et error rate par endpoint API (7 jours)';
COMMENT ON VIEW public.v_plan_distribution IS 'Répartition et croissance des plans utilisateurs';

COMMENT ON FUNCTION public.fn_dashboard_kpis()           IS 'Tous les KPIs du dashboard admin en un seul appel RPC';
COMMENT ON FUNCTION public.fn_user_cohort_retention(INT) IS 'Analyse rétention mensuelle par cohorte (usage_logs)';

-- ============================================================
-- VÉRIFICATION FINALE
-- ============================================================
DO $$
DECLARE
  tbl TEXT;
BEGIN
  FOREACH tbl IN ARRAY ARRAY['admin_users','admin_audit_log','moderation_queue','admin_settings'] LOOP
    IF NOT EXISTS (
      SELECT 1 FROM information_schema.tables
       WHERE table_schema = 'public' AND table_name = tbl
    ) THEN
      RAISE EXCEPTION 'Table manquante : %', tbl;
    END IF;
  END LOOP;
  RAISE NOTICE '✅ Migration 007 terminée avec succès — 4 tables, 5 vues, 2 fonctions créées.';
END;
$$;
