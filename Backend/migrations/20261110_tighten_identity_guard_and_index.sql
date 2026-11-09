-- The identity guard runs through its trigger only; API clients must not be
-- able to invoke its SECURITY DEFINER function directly.
REVOKE ALL ON FUNCTION public.claim_application_identity() FROM PUBLIC, anon, authenticated;

-- Support application-to-job lookups and avoid slow parent-row updates.
CREATE INDEX IF NOT EXISTS applications_job_id_idx
  ON public.applications(job_id);
