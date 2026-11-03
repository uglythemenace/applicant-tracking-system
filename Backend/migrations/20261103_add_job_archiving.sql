-- Archive closed positions without deleting applications linked to them.
alter table public.jobs
  add column if not exists is_archived boolean not null default false;

create index if not exists jobs_public_open_idx
  on public.jobs (id desc)
  where status = 'approved' and is_archived = false;
