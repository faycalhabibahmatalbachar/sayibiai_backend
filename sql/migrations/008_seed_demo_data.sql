-- ============================================================
-- MIGRATION 008 — Données de démonstration ChadGPT Admin
-- Peuple toutes les tables pour rendre le panneau admin fonctionnel.
-- ============================================================
-- NOTE IMPORTANTE :
--   On utilise session_replication_role = replica pour bypasser les FK
--   lors de l'insertion dans public.users (qui référence auth.users).
--   L'utilisateur réel existant (faycalhabib40@gmail.com) est inclus.
--   Exécuter dans Supabase SQL Editor → Run.
-- ============================================================

BEGIN;

-- Bypass FK constraints (postgres superuser uniquement — SQL Editor Supabase)
SET session_replication_role = replica;

-- ============================================================
-- 1. UTILISATEURS DE DÉMONSTRATION (public.users)
-- ============================================================
-- Inclut l'utilisateur réel existant (ON CONFLICT DO NOTHING)
-- puis ajoute 14 utilisateurs de démo.

INSERT INTO public.users
  (id, email, full_name, avatar_url, language, plan, model_preference, theme, notifications, total_tokens_used, created_at, updated_at)
VALUES
  -- Utilisateur réel existant (ne pas écraser)
  ('df8ab6da-9a9c-472f-a133-330e604dc6f2','faycalhabib40@gmail.com','Faycal Habib',NULL,'fr','free','auto','dark',true,12450,'2026-04-19 16:24:34+00','2026-04-26 16:43:31+00'),
  -- Utilisateurs Pro
  ('11111111-0000-0000-0000-000000000001','alice.martin@company.com','Alice Martin',NULL,'fr','pro','groq','dark',true,284000,'2026-01-10 09:15:00+00',NOW()),
  ('11111111-0000-0000-0000-000000000002','bob.smith@startup.io','Bob Smith',NULL,'en','pro','gemini','dark',true,195000,'2026-01-18 14:30:00+00',NOW()),
  ('11111111-0000-0000-0000-000000000003','carlos.garcia@tech.com','Carlos García',NULL,'en','pro','mistral','dark',true,421000,'2026-02-02 10:00:00+00',NOW()),
  ('11111111-0000-0000-0000-000000000004','diana.chen@research.ai','Diana Chen',NULL,'en','pro','groq','dark',true,876000,'2025-12-15 08:00:00+00',NOW()),
  ('11111111-0000-0000-0000-000000000005','emma.dubois@agence.fr','Emma Dubois',NULL,'fr','pro','auto','dark',false,98000,'2026-02-14 11:20:00+00',NOW()),
  -- Utilisateurs Enterprise
  ('11111111-0000-0000-0000-000000000006','frank.mueller@enterprise.de','Frank Müller',NULL,'en','enterprise','groq','dark',true,2450000,'2025-11-01 07:00:00+00',NOW()),
  ('11111111-0000-0000-0000-000000000007','grace.tanaka@corp.jp','Grace Tanaka',NULL,'en','enterprise','gemini','dark',true,3200000,'2025-10-20 06:30:00+00',NOW()),
  -- Utilisateurs Free
  ('11111111-0000-0000-0000-000000000008','hassan.ali@gmail.com','Hassan Ali',NULL,'ar','free','auto','dark',true,3200,'2026-03-05 12:00:00+00',NOW()),
  ('11111111-0000-0000-0000-000000000009','isabelle.roy@email.com','Isabelle Roy',NULL,'fr','free','auto','dark',false,8900,'2026-03-12 15:45:00+00',NOW()),
  ('11111111-0000-0000-0000-000000000010','james.wilson@gmail.com','James Wilson',NULL,'en','free','auto','dark',true,15400,'2026-03-20 09:00:00+00',NOW()),
  ('11111111-0000-0000-0000-000000000011','khadija.ndiaye@dakar.sn','Khadija Ndiaye',NULL,'fr','free','gemini','dark',true,4500,'2026-04-01 10:30:00+00',NOW()),
  ('11111111-0000-0000-0000-000000000012','luca.rossi@italia.it','Luca Rossi',NULL,'en','free','groq','dark',false,22000,'2026-04-05 14:00:00+00',NOW()),
  ('11111111-0000-0000-0000-000000000013','maria.silva@brasil.br','Maria Silva',NULL,'en','pro','auto','dark',true,145000,'2026-02-28 08:45:00+00',NOW()),
  ('11111111-0000-0000-0000-000000000014','omar.rashid@middleeast.ae','Omar Rashid',NULL,'ar','free','mistral','dark',true,6700,'2026-04-10 11:15:00+00',NOW()),
  ('11111111-0000-0000-0000-000000000015','sarah.johnson@consulting.com','Sarah Johnson',NULL,'en','enterprise','groq','dark',true,1800000,'2025-12-01 09:00:00+00',NOW())
ON CONFLICT (id) DO NOTHING;

-- ============================================================
-- 2. SESSIONS DE CHAT (public.chat_sessions)
-- ============================================================
INSERT INTO public.chat_sessions
  (id, user_id, title, model_used, language, total_messages, total_tokens, created_at, updated_at)
VALUES
  ('aaaaaaaa-0000-0000-0000-000000000001','df8ab6da-9a9c-472f-a133-330e604dc6f2','Comment apprendre le Python ?','groq','fr',8,3240,'2026-04-25 09:00:00+00','2026-04-25 09:45:00+00'),
  ('aaaaaaaa-0000-0000-0000-000000000002','df8ab6da-9a9c-472f-a133-330e604dc6f2','Génération de CV professionnel','gemini','fr',12,5820,'2026-04-26 10:00:00+00','2026-04-26 10:30:00+00'),
  ('aaaaaaaa-0000-0000-0000-000000000003','11111111-0000-0000-0000-000000000001','Market analysis report Q1 2026','groq','en',24,12400,'2026-04-20 08:00:00+00','2026-04-20 10:00:00+00'),
  ('aaaaaaaa-0000-0000-0000-000000000004','11111111-0000-0000-0000-000000000001','Stratégie marketing réseaux sociaux','groq','fr',18,8900,'2026-04-22 14:00:00+00','2026-04-22 15:30:00+00'),
  ('aaaaaaaa-0000-0000-0000-000000000005','11111111-0000-0000-0000-000000000002','Build SaaS product roadmap','gemini','en',31,16200,'2026-04-18 09:00:00+00','2026-04-18 11:00:00+00'),
  ('aaaaaaaa-0000-0000-0000-000000000006','11111111-0000-0000-0000-000000000003','Code review Python backend','mistral','en',15,9800,'2026-04-23 13:00:00+00','2026-04-23 14:00:00+00'),
  ('aaaaaaaa-0000-0000-0000-000000000007','11111111-0000-0000-0000-000000000004','Deep learning paper summary','groq','en',42,28000,'2026-04-15 07:00:00+00','2026-04-15 09:30:00+00'),
  ('aaaaaaaa-0000-0000-0000-000000000008','11111111-0000-0000-0000-000000000005','Rédaction contrat commercial','auto','fr',9,4200,'2026-04-24 16:00:00+00','2026-04-24 16:45:00+00'),
  ('aaaaaaaa-0000-0000-0000-000000000009','11111111-0000-0000-0000-000000000006','Enterprise API integration plan','groq','en',55,38000,'2026-04-10 08:00:00+00','2026-04-10 12:00:00+00'),
  ('aaaaaaaa-0000-0000-0000-000000000010','11111111-0000-0000-0000-000000000007','Financial analysis Q1 2026','gemini','en',38,24000,'2026-04-12 09:00:00+00','2026-04-12 11:00:00+00'),
  ('aaaaaaaa-0000-0000-0000-000000000011','11111111-0000-0000-0000-000000000008','كيف أتعلم البرمجة؟','auto','ar',6,2100,'2026-04-26 08:00:00+00','2026-04-26 08:30:00+00'),
  ('aaaaaaaa-0000-0000-0000-000000000012','11111111-0000-0000-0000-000000000013','Growth hacking strategies 2026','auto','en',20,11000,'2026-04-21 10:00:00+00','2026-04-21 11:30:00+00'),
  ('aaaaaaaa-0000-0000-0000-000000000013','11111111-0000-0000-0000-000000000015','Pitch deck for Series A','groq','en',28,18000,'2026-04-17 09:00:00+00','2026-04-17 11:00:00+00'),
  ('aaaaaaaa-0000-0000-0000-000000000014','11111111-0000-0000-0000-000000000009','Rédiger un email professionnel','auto','fr',5,1800,'2026-04-26 11:00:00+00','2026-04-26 11:20:00+00'),
  ('aaaaaaaa-0000-0000-0000-000000000015','11111111-0000-0000-0000-000000000010','How to build a mobile app','gemini','en',14,7200,'2026-04-25 15:00:00+00','2026-04-25 16:00:00+00')
ON CONFLICT (id) DO NOTHING;

-- ============================================================
-- 3. MESSAGES (public.messages)
-- ============================================================
INSERT INTO public.messages (id, session_id, role, content, tokens, model_used, created_at)
VALUES
  -- Session 1 (faycal)
  (gen_random_uuid(),'aaaaaaaa-0000-0000-0000-000000000001','user','Comment apprendre le Python efficacement en 2026 ?',18,'groq','2026-04-25 09:00:00+00'),
  (gen_random_uuid(),'aaaaaaaa-0000-0000-0000-000000000001','assistant','Pour apprendre Python efficacement en 2026, voici une feuille de route structurée : 1) Commencez par les bases (variables, conditions, boucles), 2) Pratiquez avec des projets concrets, 3) Explorez les bibliothèques populaires comme NumPy, Pandas et FastAPI...',320,'groq','2026-04-25 09:01:00+00'),
  (gen_random_uuid(),'aaaaaaaa-0000-0000-0000-000000000001','user','Quelles sont les meilleures ressources gratuites ?',14,'groq','2026-04-25 09:05:00+00'),
  (gen_random_uuid(),'aaaaaaaa-0000-0000-0000-000000000001','assistant','Les meilleures ressources gratuites pour Python : Python.org, Codecademy, freeCodeCamp, Real Python, CS50 de Harvard (gratuit sur edX), PyBites pour la pratique quotidienne...',280,'groq','2026-04-25 09:06:00+00'),
  -- Session 2 (faycal)
  (gen_random_uuid(),'aaaaaaaa-0000-0000-0000-000000000002','user','Génère-moi un CV professionnel pour un développeur Flutter junior',24,'gemini','2026-04-26 10:00:00+00'),
  (gen_random_uuid(),'aaaaaaaa-0000-0000-0000-000000000002','assistant','# CV - Développeur Flutter Junior\n\n**FAYCAL HABIB AHMAT**\nDéveloppeur Mobile Flutter | N''Djamena, Tchad\n\n## COMPÉTENCES\n- Flutter & Dart\n- FastAPI, Python\n- Firebase, Supabase\n- REST APIs, Riverpod...',580,'gemini','2026-04-26 10:02:00+00'),
  -- Session 3 (alice)
  (gen_random_uuid(),'aaaaaaaa-0000-0000-0000-000000000003','user','Analyze the Q1 2026 SaaS market trends',16,'groq','2026-04-20 08:00:00+00'),
  (gen_random_uuid(),'aaaaaaaa-0000-0000-0000-000000000003','assistant','Q1 2026 SaaS Market Analysis: The market shows strong recovery with AI-native products leading growth at 340% YoY. Key trends: 1) AI co-pilots embedded in every category, 2) Vertical SaaS dominance in healthcare and legal...',620,'groq','2026-04-20 08:02:00+00'),
  -- Session problématique (pour modération)
  (gen_random_uuid(),'aaaaaaaa-0000-0000-0000-000000000011','user','كيف أتعلم البرمجة من الصفر؟',12,'auto','2026-04-26 08:00:00+00'),
  (gen_random_uuid(),'aaaaaaaa-0000-0000-0000-000000000011','assistant','أهلاً! لتعلم البرمجة من الصفر، إليك خطوات مجربة: 1) ابدأ بـ Python - أسهل لغة للمبتدئين، 2) استخدم مواقع مثل Codecademy وfreeCodeCamp...',340,'auto','2026-04-26 08:01:00+00')
ON CONFLICT (id) DO NOTHING;

-- ============================================================
-- 4. USAGE LOGS (public.usage_logs)
-- 30 jours de données réalistes pour les graphiques
-- ============================================================

-- Insérer des logs sur les 30 derniers jours pour tous les utilisateurs
-- On génère des données journalières avec GENERATE_SERIES
INSERT INTO public.usage_logs
  (id, user_id, endpoint, model_used, tokens_used, request_duration_ms, status_code, created_at)
SELECT
  gen_random_uuid(),
  u.id,
  ep.endpoint,
  m.model,
  FLOOR(50 + RANDOM() * 2000)::INT,
  FLOOR(200 + RANDOM() * 3000)::INT,
  CASE WHEN RANDOM() < 0.03 THEN 500 WHEN RANDOM() < 0.05 THEN 400 ELSE 200 END,
  gs.day + (RANDOM() * INTERVAL '23 hours') + (RANDOM() * INTERVAL '59 minutes')
FROM
  GENERATE_SERIES(NOW() - INTERVAL '30 days', NOW(), INTERVAL '1 day') AS gs(day),
  (VALUES
    ('df8ab6da-9a9c-472f-a133-330e604dc6f2'::uuid),
    ('11111111-0000-0000-0000-000000000001'::uuid),
    ('11111111-0000-0000-0000-000000000002'::uuid),
    ('11111111-0000-0000-0000-000000000003'::uuid),
    ('11111111-0000-0000-0000-000000000004'::uuid),
    ('11111111-0000-0000-0000-000000000005'::uuid),
    ('11111111-0000-0000-0000-000000000006'::uuid),
    ('11111111-0000-0000-0000-000000000007'::uuid),
    ('11111111-0000-0000-0000-000000000008'::uuid),
    ('11111111-0000-0000-0000-000000000009'::uuid),
    ('11111111-0000-0000-0000-000000000010'::uuid),
    ('11111111-0000-0000-0000-000000000013'::uuid),
    ('11111111-0000-0000-0000-000000000015'::uuid)
  ) AS u(id),
  (VALUES
    ('/api/v1/chat/message'),
    ('/api/v1/chat/stream'),
    ('/api/v1/voice/transcribe'),
    ('/api/v1/image/generate'),
    ('/api/v1/generate/cv'),
    ('/api/v1/search/web'),
    ('/api/v1/documents/ask'),
    ('/api/v1/agent/turn')
  ) AS ep(endpoint),
  (VALUES ('groq'), ('gemini'), ('mistral'), ('groq'), ('gemini')) AS m(model)
WHERE
  -- Pro/Enterprise users: 5-20 requests/day, Free: 1-5
  RANDOM() < CASE
    WHEN u.id IN ('11111111-0000-0000-0000-000000000006'::uuid,'11111111-0000-0000-0000-000000000007'::uuid,'11111111-0000-0000-0000-000000000015'::uuid) THEN 0.7
    WHEN u.id IN ('11111111-0000-0000-0000-000000000001'::uuid,'11111111-0000-0000-0000-000000000002'::uuid,'11111111-0000-0000-0000-000000000003'::uuid,'11111111-0000-0000-0000-000000000004'::uuid,'11111111-0000-0000-0000-000000000005'::uuid,'11111111-0000-0000-0000-000000000013'::uuid) THEN 0.5
    ELSE 0.2
  END;

-- Logs additionnels aujourd'hui (pour active_users_today > 0)
INSERT INTO public.usage_logs
  (id, user_id, endpoint, model_used, tokens_used, request_duration_ms, status_code, created_at)
VALUES
  (gen_random_uuid(),'df8ab6da-9a9c-472f-a133-330e604dc6f2','/api/v1/chat/message','groq',450,380,200,NOW() - INTERVAL '30 minutes'),
  (gen_random_uuid(),'df8ab6da-9a9c-472f-a133-330e604dc6f2','/api/v1/generate/cv','gemini',820,1200,200,NOW() - INTERVAL '15 minutes'),
  (gen_random_uuid(),'11111111-0000-0000-0000-000000000001','/api/v1/chat/message','groq',680,420,200,NOW() - INTERVAL '25 minutes'),
  (gen_random_uuid(),'11111111-0000-0000-0000-000000000001','/api/v1/search/web','groq',320,290,200,NOW() - INTERVAL '10 minutes'),
  (gen_random_uuid(),'11111111-0000-0000-0000-000000000002','/api/v1/chat/stream','gemini',1240,890,200,NOW() - INTERVAL '45 minutes'),
  (gen_random_uuid(),'11111111-0000-0000-0000-000000000003','/api/v1/documents/ask','mistral',560,720,200,NOW() - INTERVAL '20 minutes'),
  (gen_random_uuid(),'11111111-0000-0000-0000-000000000004','/api/v1/chat/message','groq',2100,1050,200,NOW() - INTERVAL '5 minutes'),
  (gen_random_uuid(),'11111111-0000-0000-0000-000000000006','/api/v1/agent/turn','groq',3200,1800,200,NOW() - INTERVAL '12 minutes'),
  (gen_random_uuid(),'11111111-0000-0000-0000-000000000007','/api/v1/chat/message','gemini',1800,940,200,NOW() - INTERVAL '35 minutes'),
  (gen_random_uuid(),'11111111-0000-0000-0000-000000000008','/api/v1/chat/message','auto',280,310,200,NOW() - INTERVAL '50 minutes'),
  (gen_random_uuid(),'11111111-0000-0000-0000-000000000013','/api/v1/chat/message','auto',740,480,200,NOW() - INTERVAL '18 minutes'),
  (gen_random_uuid(),'11111111-0000-0000-0000-000000000015','/api/v1/chat/stream','groq',1650,780,200,NOW() - INTERVAL '8 minutes'),
  -- Quelques erreurs pour les métriques
  (gen_random_uuid(),'11111111-0000-0000-0000-000000000010','/api/v1/image/generate','groq',0,5000,500,NOW() - INTERVAL '40 minutes'),
  (gen_random_uuid(),'11111111-0000-0000-0000-000000000012','/api/v1/voice/transcribe','groq',0,0,400,NOW() - INTERVAL '55 minutes');

-- Mettre à jour total_tokens_used pour les utilisateurs
UPDATE public.users u
SET total_tokens_used = (
  SELECT COALESCE(SUM(ul.tokens_used), 0)
  FROM public.usage_logs ul
  WHERE ul.user_id = u.id
)
WHERE u.id IN (
  'df8ab6da-9a9c-472f-a133-330e604dc6f2',
  '11111111-0000-0000-0000-000000000001',
  '11111111-0000-0000-0000-000000000002',
  '11111111-0000-0000-0000-000000000003',
  '11111111-0000-0000-0000-000000000004',
  '11111111-0000-0000-0000-000000000005',
  '11111111-0000-0000-0000-000000000006',
  '11111111-0000-0000-0000-000000000007',
  '11111111-0000-0000-0000-000000000008',
  '11111111-0000-0000-0000-000000000009',
  '11111111-0000-0000-0000-000000000010',
  '11111111-0000-0000-0000-000000000013',
  '11111111-0000-0000-0000-000000000015'
);

-- ============================================================
-- 5. MODÉRATION (public.moderation_queue)
-- ============================================================
INSERT INTO public.moderation_queue
  (id, user_id, session_id, message_id, content_type, content_preview,
   ai_scores, ai_confidence, priority, status, flagged_at)
VALUES
  (gen_random_uuid(),'11111111-0000-0000-0000-000000000010',NULL,NULL,'text',
   'Comment pirater un compte Instagram facilement ? Donne-moi des méthodes détaillées...',
   '{"violence":5,"sexual":2,"hate":8,"self_harm":0,"spam":12}'::JSONB, 78, 85, 'pending',
   NOW() - INTERVAL '2 hours'),
  (gen_random_uuid(),'11111111-0000-0000-0000-000000000012',NULL,NULL,'text',
   'PROMO !!! Gagnez 500€ PAR JOUR depuis chez vous ! Cliquez ici maintenant...',
   '{"violence":0,"sexual":0,"hate":2,"self_harm":0,"spam":95}'::JSONB, 96, 70, 'pending',
   NOW() - INTERVAL '4 hours'),
  (gen_random_uuid(),'11111111-0000-0000-0000-000000000014',NULL,NULL,'text',
   'Génère un contenu explicite pour adultes avec des descriptions détaillées...',
   '{"violence":8,"sexual":87,"hate":3,"self_harm":0,"spam":5}'::JSONB, 94, 95, 'pending',
   NOW() - INTERVAL '1 hour'),
  (gen_random_uuid(),'df8ab6da-9a9c-472f-a133-330e604dc6f2','aaaaaaaa-0000-0000-0000-000000000001',NULL,'text',
   'Comment apprendre le Python efficacement en 2026 ?',
   '{"violence":0,"sexual":0,"hate":0,"self_harm":0,"spam":0}'::JSONB, 99, 10, 'approved',
   NOW() - INTERVAL '1 day'),
  (gen_random_uuid(),'11111111-0000-0000-0000-000000000009',NULL,NULL,'text',
   'Aide-moi à créer un faux diplôme universitaire pour tromper mon employeur...',
   '{"violence":2,"sexual":0,"hate":5,"self_harm":0,"spam":15}'::JSONB, 82, 75, 'rejected',
   NOW() - INTERVAL '6 hours'),
  (gen_random_uuid(),'11111111-0000-0000-0000-000000000011',NULL,NULL,'text',
   'أريد معرفة كيفية الوصول إلى معلومات شخصية لشخص ما...',
   '{"violence":10,"sexual":0,"hate":12,"self_harm":0,"spam":5}'::JSONB, 71, 60, 'pending',
   NOW() - INTERVAL '3 hours'),
  (gen_random_uuid(),'11111111-0000-0000-0000-000000000010',NULL,NULL,'text',
   'Je veux en finir, dis-moi comment je peux disparaître pour toujours...',
   '{"violence":20,"sexual":0,"hate":5,"self_harm":92,"spam":0}'::JSONB, 97, 100, 'escalated',
   NOW() - INTERVAL '30 minutes'),
  (gen_random_uuid(),'11111111-0000-0000-0000-000000000013',NULL,NULL,'text',
   'Generate 1000 fake product reviews for my Amazon store to boost sales...',
   '{"violence":0,"sexual":0,"hate":0,"self_harm":0,"spam":88}'::JSONB, 91, 65, 'pending',
   NOW() - INTERVAL '5 hours');

-- ============================================================
-- 6. NOTIFICATIONS (public.notifications)
-- ============================================================
INSERT INTO public.notifications (id, user_id, title, body, data, sent_at)
VALUES
  (gen_random_uuid(),'df8ab6da-9a9c-472f-a133-330e604dc6f2','Bienvenue sur ChadGPT !','Votre compte est activé. Commencez à explorer les fonctionnalités IA.',NULL,'2026-04-19 16:30:00+00'),
  (gen_random_uuid(),'df8ab6da-9a9c-472f-a133-330e604dc6f2','Votre CV a été généré','Téléchargez votre CV professionnel depuis l''application.',NULL,'2026-04-26 10:05:00+00'),
  (gen_random_uuid(),'11111111-0000-0000-0000-000000000001','Rapport mensuel disponible','Votre rapport d''analyse du marché est prêt.',NULL,'2026-04-20 10:30:00+00'),
  (gen_random_uuid(),'11111111-0000-0000-0000-000000000006','Usage alert','You have used 80% of your monthly quota.',NULL,'2026-04-25 08:00:00+00'),
  (gen_random_uuid(),'11111111-0000-0000-0000-000000000007','Renewal reminder','Your Enterprise subscription renews in 7 days.',NULL,'2026-04-24 09:00:00+00')
ON CONFLICT (id) DO NOTHING;

-- ============================================================
-- 7. DOCUMENTS (public.documents)
-- ============================================================
INSERT INTO public.documents
  (id, user_id, filename, file_type, file_size, storage_path, extracted_text, page_count, created_at)
VALUES
  (gen_random_uuid(),'df8ab6da-9a9c-472f-a133-330e604dc6f2','rapport_stage.pdf','pdf',245000,'uploads/df8ab6da/rapport_stage.pdf','Rapport de stage - Développement mobile Flutter...', 12,'2026-04-20 14:00:00+00'),
  (gen_random_uuid(),'11111111-0000-0000-0000-000000000001','market_analysis.docx','docx',89000,'uploads/alice/market_analysis.docx','Market Analysis Q1 2026 - SaaS trends...', 8,'2026-04-18 09:00:00+00'),
  (gen_random_uuid(),'11111111-0000-0000-0000-000000000002','product_roadmap.pdf','pdf',156000,'uploads/bob/product_roadmap.pdf','Product Roadmap 2026-2027...', 15,'2026-04-15 11:00:00+00'),
  (gen_random_uuid(),'11111111-0000-0000-0000-000000000004','research_paper.pdf','pdf',890000,'uploads/diana/research_paper.pdf','Deep Learning for Natural Language Processing...', 42,'2026-04-10 07:00:00+00'),
  (gen_random_uuid(),'11111111-0000-0000-0000-000000000006','enterprise_contract.pdf','pdf',320000,'uploads/frank/enterprise_contract.pdf','Service Agreement - Enterprise Plan...', 28,'2026-03-01 09:00:00+00')
ON CONFLICT (id) DO NOTHING;

-- ============================================================
-- 8. FICHIERS GÉNÉRÉS (public.generated_files)
-- ============================================================
INSERT INTO public.generated_files
  (id, user_id, file_type, filename, storage_path, prompt_used, session_id, created_at)
VALUES
  (gen_random_uuid(),'df8ab6da-9a9c-472f-a133-330e604dc6f2','cv','cv_faycal_2026.pdf','generated/df8ab6da/cv_faycal_2026.pdf','CV développeur Flutter junior','aaaaaaaa-0000-0000-0000-000000000002','2026-04-26 10:05:00+00'),
  (gen_random_uuid(),'11111111-0000-0000-0000-000000000001','report','market_report_q1.pdf','generated/alice/market_report_q1.pdf','Market analysis Q1 2026','aaaaaaaa-0000-0000-0000-000000000003','2026-04-20 08:45:00+00'),
  (gen_random_uuid(),'11111111-0000-0000-0000-000000000005','letter','lettre_mission.docx','generated/emma/lettre_mission.docx','Lettre de mission consultant','aaaaaaaa-0000-0000-0000-000000000008','2026-04-24 16:20:00+00'),
  (gen_random_uuid(),'11111111-0000-0000-0000-000000000013','report','growth_strategy_2026.pdf','generated/maria/growth_strategy_2026.pdf','Growth hacking strategy report','aaaaaaaa-0000-0000-0000-000000000012','2026-04-21 11:00:00+00'),
  (gen_random_uuid(),'11111111-0000-0000-0000-000000000015','report','pitch_deck_series_a.pdf','generated/sarah/pitch_deck_series_a.pdf','Series A pitch deck for AI startup','aaaaaaaa-0000-0000-0000-000000000013','2026-04-17 10:30:00+00')
ON CONFLICT (id) DO NOTHING;

-- ============================================================
-- 9. AUDIT LOG ADMIN (public.admin_audit_log)
-- ============================================================
INSERT INTO public.admin_audit_log
  (admin_id, admin_email, action, entity_type, entity_id, changes, result, created_at)
SELECT
  au.id,
  au.email,
  v.action,
  v.entity_type,
  v.entity_id,
  v.changes::JSONB,
  'success',
  v.created_at
FROM public.admin_users au
CROSS JOIN (VALUES
  ('login_success',   'admin_users',      'admin_001',    '{}',                            NOW() - INTERVAL '2 hours'),
  ('update_user',     'users',            '11111111-0000-0000-0000-000000000001', '{"plan":"pro"}', NOW() - INTERVAL '3 hours'),
  ('moderation_reject','moderation_queue','mod-001',      '{"decision":"reject"}',          NOW() - INTERVAL '4 hours'),
  ('update_setting',  'admin_settings',   'rate_limit',   '{"value":"1000"}',               NOW() - INTERVAL '5 hours'),
  ('ban_user',        'users',            '11111111-0000-0000-0000-000000000010', '{"reason":"spam"}', NOW() - INTERVAL '1 day'),
  ('export_users',    'users',            'bulk',         '{"count":150}',                  NOW() - INTERVAL '2 days'),
  ('login_success',   'admin_users',      'admin_001',    '{}',                            NOW() - INTERVAL '1 day')
) AS v(action, entity_type, entity_id, changes, created_at)
WHERE au.email = 'admin@chadgpt.ai';

-- ============================================================
-- ÉTAPE FINALE : Réactiver les FK constraints
-- ============================================================
SET session_replication_role = DEFAULT;

-- ============================================================
-- VÉRIFICATION
-- ============================================================
DO $$
DECLARE
  n_users    INT;
  n_logs     INT;
  n_sessions INT;
  n_mod      INT;
BEGIN
  SELECT COUNT(*) INTO n_users    FROM public.users;
  SELECT COUNT(*) INTO n_logs     FROM public.usage_logs;
  SELECT COUNT(*) INTO n_sessions FROM public.chat_sessions;
  SELECT COUNT(*) INTO n_mod      FROM public.moderation_queue;

  RAISE NOTICE '============================================';
  RAISE NOTICE '✅ Seed 008 terminé avec succès !';
  RAISE NOTICE '   Utilisateurs    : %', n_users;
  RAISE NOTICE '   Sessions chat   : %', n_sessions;
  RAISE NOTICE '   Usage logs      : %', n_logs;
  RAISE NOTICE '   File modération : %', n_mod;
  RAISE NOTICE '============================================';
  RAISE NOTICE 'Connexion admin → admin@chadgpt.ai / admin123';
END;
$$;

COMMIT;
