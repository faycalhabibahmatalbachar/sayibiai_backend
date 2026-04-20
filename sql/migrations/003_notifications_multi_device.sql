-- Multi-device FCM tokens + DLQ notifications (idempotent)

CREATE TABLE IF NOT EXISTS public.fcm_device_tokens (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES public.users(id) ON DELETE CASCADE NOT NULL,
  device_id TEXT NOT NULL,
  platform TEXT,
  token TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (user_id, device_id)
);

CREATE INDEX IF NOT EXISTS idx_fcm_device_tokens_user
  ON public.fcm_device_tokens (user_id, updated_at DESC);

DROP TRIGGER IF EXISTS fcm_device_tokens_updated_at ON public.fcm_device_tokens;
CREATE TRIGGER fcm_device_tokens_updated_at
  BEFORE UPDATE ON public.fcm_device_tokens
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TABLE IF NOT EXISTS public.notification_dlq (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES public.users(id) ON DELETE CASCADE NOT NULL,
  token_suffix TEXT,
  title TEXT,
  body TEXT,
  error_message TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notification_dlq_user_created
  ON public.notification_dlq (user_id, created_at DESC);
