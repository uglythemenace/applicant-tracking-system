-- Empty staging and new environments need the core tables before the
-- feature migrations in this directory can be applied. This defines schema
-- only; it intentionally does not copy production applicant or job records.

CREATE TABLE IF NOT EXISTS public.jobs (
  id serial PRIMARY KEY,
  title character varying NOT NULL,
  description text,
  department character varying,
  created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
  status text DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS public.applicants (
  id serial PRIMARY KEY,
  full_name character varying NOT NULL,
  email character varying NOT NULL UNIQUE,
  phone character varying,
  resume_url text,
  created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS public.applications (
  id serial PRIMARY KEY,
  job_id integer REFERENCES public.jobs(id),
  candidate_name character varying NOT NULL,
  email character varying NOT NULL,
  resume_url text,
  status character varying DEFAULT 'pending',
  created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
  tracking_code text
);

ALTER TABLE public.jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.applicants ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.applications ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.jobs, public.applicants, public.applications FROM anon, authenticated;
GRANT ALL ON public.jobs, public.applicants, public.applications TO service_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO service_role;
