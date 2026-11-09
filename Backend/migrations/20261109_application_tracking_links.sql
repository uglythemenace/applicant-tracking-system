-- Give each application a high-entropy bearer token for private tracking links.
-- Existing applications receive tokens too, while the tracking-code flow remains available.
ALTER TABLE public.applications
  ADD COLUMN IF NOT EXISTS track_token uuid;

UPDATE public.applications
SET track_token = gen_random_uuid()
WHERE track_token IS NULL;

ALTER TABLE public.applications
  ALTER COLUMN track_token SET DEFAULT gen_random_uuid(),
  ALTER COLUMN track_token SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS applications_track_token_uidx
  ON public.applications(track_token);
