-- =============================================================================
-- Migration 012 — engagement_series réel (agrégat usage_logs, 7 jours).
-- Prérequis : 011_retention_ai_enriched_view.sql + données dans usage_logs.
-- Ré-exécutable : met à jour les séries au fil de l’eau (job hebdo recommandé).
-- =============================================================================

INSERT INTO public.user_ml_profiles (user_id)
SELECT u.id FROM public.users u
ON CONFLICT (user_id) DO NOTHING;

UPDATE public.user_ml_profiles p
SET engagement_series = agg.series
FROM (
  SELECT
    p2.user_id,
    to_jsonb(array_agg(daily.cnt ORDER BY daily.idx)) AS series
  FROM public.user_ml_profiles p2
  CROSS JOIN LATERAL (
    SELECT
      g.idx,
      COUNT(ul.id)::int AS cnt
    FROM generate_series(0, 6) AS g(idx)
    LEFT JOIN public.usage_logs ul
      ON ul.user_id = p2.user_id
     AND ul.created_at::date = (CURRENT_DATE - g.idx::int)
    GROUP BY g.idx
  ) AS daily
  GROUP BY p2.user_id
) AS agg
WHERE p.user_id = agg.user_id;
