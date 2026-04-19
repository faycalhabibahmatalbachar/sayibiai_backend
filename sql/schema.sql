-- Schéma indicatif Supabase / PostgreSQL pour SAYIBI AI
-- À exécuter dans l’éditeur SQL Supabase (adapter aux besoins RLS).

create extension if not exists "uuid-ossp";

create table if not exists public.users (
  id uuid primary key default uuid_generate_v4(),
  email text unique,
  name text,
  plan text default 'free',
  language text default 'fr',
  theme text default 'dark',
  notifications boolean default true,
  model_preference text default 'auto',
  created_at timestamptz default now()
);

create table if not exists public.conversations (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid not null references public.users(id) on delete cascade,
  title text,
  model_used text,
  created_at timestamptz default now()
);

create table if not exists public.messages (
  id uuid primary key default uuid_generate_v4(),
  conv_id uuid not null references public.conversations(id) on delete cascade,
  role text not null,
  content text not null,
  tokens int,
  created_at timestamptz default now()
);

create table if not exists public.documents (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid not null references public.users(id) on delete cascade,
  filename text,
  r2_url text,
  extracted_text text,
  embedding_id text,
  created_at timestamptz default now()
);

create table if not exists public.generated_files (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid not null references public.users(id) on delete cascade,
  type text,
  r2_url text,
  prompt_used text,
  created_at timestamptz default now()
);

create table if not exists public.usage_logs (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid not null references public.users(id) on delete cascade,
  endpoint text,
  tokens_used int,
  model text,
  created_at timestamptz default now()
);

create index if not exists idx_messages_conv on public.messages(conv_id);
create index if not exists idx_conversations_user on public.conversations(user_id);
create index if not exists idx_usage_user on public.usage_logs(user_id);
