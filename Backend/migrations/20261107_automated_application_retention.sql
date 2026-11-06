-- Automatically erase finalized applications after 12 months. This delegates
-- each record to the same deletion function used by staff so identity claims,
-- related history, audit details, and résumé cleanup are handled consistently.
CREATE OR REPLACE FUNCTION public.purge_expired_applications_12_months()
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_application_id integer;
  v_deleted_count integer := 0;
  v_result jsonb;
BEGIN
  FOR v_application_id IN
    SELECT id
    FROM public.applications
    WHERE status IN ('accepted', 'rejected', 'withdrawn')
      AND coalesce(status_updated_at, created_at) <= now() - interval '12 months'
    ORDER BY coalesce(status_updated_at, created_at), id
    FOR UPDATE SKIP LOCKED
  LOOP
    v_result := public.delete_application_for_retention(
      v_application_id,
      'retention-policy@system.invalid'
    );
    IF v_result IS NOT NULL AND coalesce((v_result->>'deleted')::boolean, false) THEN
      v_deleted_count := v_deleted_count + 1;
    END IF;
  END LOOP;

  RETURN v_deleted_count;
END;
$$;

REVOKE ALL ON FUNCTION public.purge_expired_applications_12_months() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.purge_expired_applications_12_months() TO service_role;
