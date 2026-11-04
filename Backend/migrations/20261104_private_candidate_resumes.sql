-- Store applicant CVs privately; only the backend service role can access objects.
ALTER TABLE public.applications
  ADD COLUMN IF NOT EXISTS resume_path text;

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
  'candidate-resumes',
  'candidate-resumes',
  false,
  8388608,
  ARRAY[
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
  ]
)
ON CONFLICT (id) DO UPDATE
SET public = false,
    file_size_limit = EXCLUDED.file_size_limit,
    allowed_mime_types = EXCLUDED.allowed_mime_types;

-- No anon or authenticated storage.objects policies are created. The server
-- uses its Supabase service-role key for uploads and issues short-lived signed
-- links only after staff authentication.
