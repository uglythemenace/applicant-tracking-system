-- Optional applicant phone and text-message consent. Safe to run on existing databases.
alter table public.applications
  add column if not exists phone_number text;

alter table public.applications
  add column if not exists sms_updates_consent boolean not null default false;

-- Keep normalized claims separately so one email or phone can only be claimed
-- once going forward, even when older application rows contain duplicates.
create table if not exists public.application_identity_claims (
  claim_type text not null check (claim_type in ('email', 'phone')),
  normalized_value text not null,
  created_at timestamptz not null default now(),
  primary key (claim_type, normalized_value)
);

insert into public.application_identity_claims (claim_type, normalized_value)
select 'email', lower(trim(email))
from public.applications
where nullif(trim(email), '') is not null
group by lower(trim(email))
on conflict do nothing;

insert into public.application_identity_claims (claim_type, normalized_value)
select 'phone', '+' || regexp_replace(trim(phone_number), '[^0-9]', '', 'g')
from public.applications
where nullif(trim(phone_number), '') is not null
group by '+' || regexp_replace(trim(phone_number), '[^0-9]', '', 'g')
on conflict do nothing;

alter table public.application_identity_claims enable row level security;
revoke all on public.application_identity_claims from anon, authenticated;
grant all on public.application_identity_claims to service_role;

create or replace function public.claim_application_identity()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  normalized_email text;
  normalized_phone text;
begin
  normalized_email := lower(trim(new.email));
  insert into public.application_identity_claims (claim_type, normalized_value)
  values ('email', normalized_email)
  on conflict do nothing;
  if not found then
    raise exception using errcode = '23505', message = 'APPLICATION_EMAIL_ALREADY_USED';
  end if;
  new.email := normalized_email;

  if nullif(trim(new.phone_number), '') is not null then
    normalized_phone := '+' || regexp_replace(trim(new.phone_number), '[^0-9]', '', 'g');
    insert into public.application_identity_claims (claim_type, normalized_value)
    values ('phone', normalized_phone)
    on conflict do nothing;
    if not found then
      raise exception using errcode = '23505', message = 'APPLICATION_PHONE_ALREADY_USED';
    end if;
    new.phone_number := normalized_phone;
  end if;
  return new;
end;
$$;

drop trigger if exists application_identity_guard on public.applications;
create trigger application_identity_guard
before insert on public.applications
for each row execute function public.claim_application_identity();

-- Store keyed hashes only. Duplicate submission attempts are counted per
-- already-used email or phone; the fourth within a 10-minute window locks it.
create table if not exists public.application_duplicate_attempts (
  key_hash text primary key check (key_hash ~ '^[0-9a-f]{64}$'),
  attempt_count integer not null default 0,
  window_started_at timestamptz not null default now(),
  locked_until timestamptz,
  updated_at timestamptz not null default now()
);

alter table public.application_duplicate_attempts enable row level security;
revoke all on public.application_duplicate_attempts from anon, authenticated;
grant all on public.application_duplicate_attempts to service_role;

create or replace function public.check_application_duplicate_cooldown(p_key_hashes text[])
returns integer
language sql
security definer
set search_path = pg_catalog, public
as $$
  select coalesce(
    ceil(extract(epoch from (max(locked_until) - now())))::integer,
    0
  )
  from public.application_duplicate_attempts
  where key_hash = any(coalesce(p_key_hashes, array[]::text[]))
    and locked_until > now();
$$;

create or replace function public.record_application_duplicate_attempt(p_key_hash text)
returns integer
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  current_lock timestamptz;
begin
  delete from public.application_duplicate_attempts
  where updated_at < now() - interval '1 day';

  insert into public.application_duplicate_attempts as existing
    (key_hash, attempt_count, window_started_at, locked_until, updated_at)
  values (p_key_hash, 1, now(), null, now())
  on conflict (key_hash) do update set
    attempt_count = case
      when existing.window_started_at <= now() - interval '10 minutes' then 1
      else existing.attempt_count + 1
    end,
    window_started_at = case
      when existing.window_started_at <= now() - interval '10 minutes' then now()
      else existing.window_started_at
    end,
    locked_until = case
      when existing.locked_until > now() then existing.locked_until
      when existing.window_started_at <= now() - interval '10 minutes' then null
      when existing.attempt_count + 1 > 3 then now() + interval '10 minutes'
      else null
    end,
    updated_at = now()
  returning locked_until into current_lock;

  return coalesce(ceil(extract(epoch from (current_lock - now())))::integer, 0);
end;
$$;

revoke all on function public.check_application_duplicate_cooldown(text[]) from public, anon, authenticated;
revoke all on function public.record_application_duplicate_attempt(text) from public, anon, authenticated;
grant execute on function public.check_application_duplicate_cooldown(text[]) to service_role;
grant execute on function public.record_application_duplicate_attempt(text) to service_role;
