-- Fresh Jobs Tracker: run this once in Supabase -> SQL Editor.
-- Safe to re-run (uses IF NOT EXISTS where possible).

create table if not exists sources (
  id text primary key,                 -- 'greenhouse', 'lever', ...
  name text not null,
  enabled boolean not null default true,
  last_checked_at timestamptz,
  last_success_at timestamptz,
  last_error text
);

-- Which company boards to poll (user-editable, no code change needed)
create table if not exists company_boards (
  id bigint generated always as identity primary key,
  source_id text not null references sources(id),
  board_token text not null,           -- e.g. 'stripe' for boards.greenhouse.io/stripe
  company_name text not null,
  enabled boolean not null default true,
  last_checked_at timestamptz,
  last_success_at timestamptz,
  last_error text,
  unique (source_id, board_token)
);

create table if not exists profiles (
  id bigint generated always as identity primary key,
  name text not null,
  active boolean not null default true,
  include_keywords text[] not null default '{}',   -- job must contain ANY (title+description); empty = no requirement
  exclude_keywords text[] not null default '{}',   -- rejected if found in title
  states text[] not null default '{}',             -- e.g. {'CA','TX'}; empty = all US
  workplace_types text[] not null default '{}',    -- remote/hybrid/onsite; empty = all
  experience_levels text[] not null default '{}',  -- empty = all
  employment_types text[] not null default '{}',
  include_unclear_location boolean not null default false,
  max_age_days int default 14,                     -- skip jobs whose KNOWN posting date is older; null = no limit
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists profile_titles (
  id bigint generated always as identity primary key,
  profile_id bigint not null references profiles(id) on delete cascade,
  title text not null,
  enabled boolean not null default true,
  unique (profile_id, title)
);

create table if not exists jobs (
  id bigint generated always as identity primary key,
  source_id text not null references sources(id),
  source_job_id text not null,
  board_token text not null,
  title text not null,
  company text not null,
  location text,
  city text,
  state text,
  country text,                        -- 'US' or null when unclear
  workplace_type text not null default 'unspecified',  -- remote/hybrid/onsite/unspecified
  employment_type text not null default 'unspecified',
  experience_level text not null default 'unspecified',
  description text,
  application_url text not null,
  posted_at timestamptz,               -- ONLY set when the source provides it. Never guessed.
  first_detected_at timestamptz not null default now(),
  last_updated_at timestamptz,
  last_verified_at timestamptz not null default now(),
  status text not null default 'active',  -- active / closed
  closed_at timestamptz,
  profile_ids bigint[] not null default '{}',
  fingerprint text not null,           -- sha1(company|title|location) for cross-source dedupe (Phase 3)
  unique (source_id, source_job_id)
);
create index if not exists jobs_status_posted on jobs (status, posted_at desc);
create index if not exists jobs_status_detected on jobs (status, first_detected_at desc);
create index if not exists jobs_fingerprint on jobs (fingerprint);

create table if not exists collection_runs (
  id bigint generated always as identity primary key,
  source_id text not null,
  board_token text,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  fetched int default 0,
  matched int default 0,
  inserted int default 0,
  updated int default 0,
  closed int default 0,
  error text
);

-- Security: lock everything down. Collector uses the service_role key (bypasses RLS).
-- The public site may only read ACTIVE jobs with the anon key. Nothing else is readable or writable.
alter table sources enable row level security;
alter table company_boards enable row level security;
alter table profiles enable row level security;
alter table profile_titles enable row level security;
alter table jobs enable row level security;
alter table collection_runs enable row level security;

drop policy if exists "public read active jobs" on jobs;
create policy "public read active jobs" on jobs for select to anon using (status = 'active');

-- Seeds
insert into sources (id, name) values ('greenhouse', 'Greenhouse') on conflict do nothing;

-- Example boards. NOT verified: the collector logs a clear error for any token that 404s.
insert into company_boards (source_id, board_token, company_name) values
  ('greenhouse','stripe','Stripe'),
  ('greenhouse','airbnb','Airbnb'),
  ('greenhouse','databricks','Databricks'),
  ('greenhouse','discord','Discord'),
  ('greenhouse','figma','Figma')
on conflict do nothing;

with p as (
  insert into profiles (name, exclude_keywords)
  select 'Software Engineering', array['sales','recruiter','technical support','it support',
    'customer service','qa','quality assurance','project manager','product manager','manager',
    'sales engineer','solutions engineer']
  where not exists (select 1 from profiles) returning id
)
insert into profile_titles (profile_id, title)
select p.id, t from p, unnest(array[
  'Software Engineer','Software Developer','Software Development Engineer','SDE',
  'Frontend Engineer','Frontend Developer','Backend Engineer','Backend Developer',
  'Full Stack Engineer','Full Stack Developer']) as t;

-- ===== Phase 2 additions =====
insert into sources (id, name) values
  ('lever','Lever'), ('ashby','Ashby'), ('workable','Workable')
on conflict do nothing;

-- Starter company boards. NONE of these tokens are verified: a wrong one just shows an error
-- in the board_health view and never stops the others. Delete or disable the ones that fail.
insert into company_boards (source_id, board_token, company_name) values
  ('greenhouse','anthropic','Anthropic'), ('greenhouse','coinbase','Coinbase'),
  ('greenhouse','reddit','Reddit'),       ('greenhouse','pinterest','Pinterest'),
  ('greenhouse','robinhood','Robinhood'), ('greenhouse','cloudflare','Cloudflare'),
  ('greenhouse','datadog','Datadog'),     ('greenhouse','gitlab','GitLab'),
  ('greenhouse','mongodb','MongoDB'),     ('greenhouse','okta','Okta'),
  ('greenhouse','lyft','Lyft'),           ('greenhouse','doordash','DoorDash'),
  ('greenhouse','duolingo','Duolingo'),   ('greenhouse','asana','Asana'),
  ('greenhouse','dropbox','Dropbox'),     ('greenhouse','twilio','Twilio'),
  ('greenhouse','brex','Brex'),           ('greenhouse','vercel','Vercel'),
  ('lever','palantir','Palantir'),        ('lever','spotify','Spotify'),
  ('lever','plaid','Plaid'),
  ('ashby','openai','OpenAI'),            ('ashby','notion','Notion'),
  ('ashby','ramp','Ramp'),                ('ashby','linear','Linear'),
  ('ashby','supabase','Supabase'),        ('ashby','deel','Deel'),
  ('ashby','perplexity','Perplexity'),    ('ashby','replit','Replit'),
  ('ashby','snowflake','Snowflake'),      ('ashby','vanta','Vanta'),
  ('ashby','zapier','Zapier')
on conflict do nothing;

-- Easy reading views (open them in Table Editor)
drop view if exists latest_jobs;
create view latest_jobs with (security_invoker = true) as
select company, title, location, workplace_type, experience_level, employment_type,
       posted_at, first_detected_at, application_url, source_id
from jobs
where status = 'active'
order by first_detected_at desc, posted_at desc nulls last;

drop view if exists board_health;
create view board_health with (security_invoker = true) as
select source_id, company_name, board_token, enabled, last_success_at, last_error
from company_boards
order by (last_error is null), source_id, company_name;   -- failing boards first

-- ===== Phase 3 additions =====

-- Your chosen window: 21 days
alter table profiles alter column max_age_days set default 21;
update profiles set max_age_days = 21;

drop view if exists latest_jobs;
create view latest_jobs with (security_invoker = true) as
with cut as (
  -- "last session" ended at 2:00 AM IST = 20:30 UTC. Anything detected after that is new this session.
  select (
    (date_trunc('day', now() at time zone 'utc') + interval '20 hours 30 minutes')
    - case when (now() at time zone 'utc')::time < time '20:30' then interval '1 day' else interval '0 day' end
  ) at time zone 'utc' as session_start
),
base as (
  select j.*,
         coalesce(j.posted_at, j.first_detected_at) as effective_at,
         (j.posted_at is not null) as has_posted_date,
         greatest(0, extract(epoch from (now() - coalesce(j.posted_at, j.first_detected_at))) / 3600.0) as age_hours
  from jobs j
  where j.status = 'active'
    -- Cross-source dedupe: hide a job if the SAME company+title+location is already active on a
    -- DIFFERENT source and was detected earlier. Same-source twins are kept (could be separate openings).
    and not exists (
      select 1 from jobs o
      where o.fingerprint = j.fingerprint and o.status = 'active' and o.source_id <> j.source_id
        and (o.first_detected_at, o.id) < (j.first_detected_at, j.id)
    )
)
select
  b.company, b.title, b.location, b.workplace_type, b.experience_level, b.employment_type,
  case when b.age_hours < 3   then 'last_3h'
       when b.age_hours < 24  then 'last_24h'
       when b.age_hours < 72  then 'last_3d'
       when b.age_hours < 168 then 'last_7d'
       else 'older' end as freshness,
  (case when b.has_posted_date then 'Posted ' else 'First seen ' end)
    || (case when b.age_hours < 1  then 'under 1h'
             when b.age_hours < 24 then floor(b.age_hours)::int::text || 'h'
             else floor(b.age_hours / 24)::int::text || 'd' end)
    || ' ago' as freshness_label,
  (b.first_detected_at > c.session_start) as new_this_session,
  (r.earlier_seen is not null) as possible_repost,   -- an older, now-closed twin exists: may be a re-listing
  b.posted_at, b.first_detected_at, b.application_url, b.source_id
from base b
cross join cut c
left join lateral (
  select min(o.first_detected_at) as earlier_seen
  from jobs o
  where o.fingerprint = b.fingerprint and o.id <> b.id and o.status = 'closed'
    and o.first_detected_at < b.first_detected_at
) r on true
order by b.first_detected_at desc, b.effective_at desc;

-- ===== Phase 3.5 additions =====

alter table jobs add column if not exists location_confidence text not null default 'unclear';
alter table collection_runs add column if not exists rejected_location int default 0;
alter table collection_runs add column if not exists rejected_samples jsonb;

-- Jobs saved so far were accepted under the strict rule, so their country was explicit.
update jobs set location_confidence = 'explicit' where country = 'US' and location_confidence = 'unclear';

-- Rebuild latest_jobs with location_confidence added at the end
drop view if exists latest_jobs;
create view latest_jobs with (security_invoker = true) as
with cut as (
  -- "last session" ended at 2:00 AM IST = 20:30 UTC. Anything detected after that is new this session.
  select (
    (date_trunc('day', now() at time zone 'utc') + interval '20 hours 30 minutes')
    - case when (now() at time zone 'utc')::time < time '20:30' then interval '1 day' else interval '0 day' end
  ) at time zone 'utc' as session_start
),
base as (
  select j.*,
         coalesce(j.posted_at, j.first_detected_at) as effective_at,
         (j.posted_at is not null) as has_posted_date,
         greatest(0, extract(epoch from (now() - coalesce(j.posted_at, j.first_detected_at))) / 3600.0) as age_hours
  from jobs j
  where j.status = 'active'
    -- Cross-source dedupe: hide a job if the SAME company+title+location is already active on a
    -- DIFFERENT source and was detected earlier. Same-source twins are kept (could be separate openings).
    and not exists (
      select 1 from jobs o
      where o.fingerprint = j.fingerprint and o.status = 'active' and o.source_id <> j.source_id
        and (o.first_detected_at, o.id) < (j.first_detected_at, j.id)
    )
)
select
  b.company, b.title, b.location, b.workplace_type, b.experience_level, b.employment_type,
  case when b.age_hours < 3   then 'last_3h'
       when b.age_hours < 24  then 'last_24h'
       when b.age_hours < 72  then 'last_3d'
       when b.age_hours < 168 then 'last_7d'
       else 'older' end as freshness,
  (case when b.has_posted_date then 'Posted ' else 'First seen ' end)
    || (case when b.age_hours < 1  then 'under 1h'
             when b.age_hours < 24 then floor(b.age_hours)::int::text || 'h'
             else floor(b.age_hours / 24)::int::text || 'd' end)
    || ' ago' as freshness_label,
  (b.first_detected_at > c.session_start) as new_this_session,
  (r.earlier_seen is not null) as possible_repost,   -- an older, now-closed twin exists: may be a re-listing
  b.posted_at, b.first_detected_at, b.application_url, b.source_id,
  b.location_confidence
from base b
cross join cut c
left join lateral (
  select min(o.first_detected_at) as earlier_seen
  from jobs o
  where o.fingerprint = b.fingerprint and o.id <> b.id and o.status = 'closed'
    and o.first_detected_at < b.first_detected_at
) r on true
order by b.first_detected_at desc, b.effective_at desc;

-- What the location filter rejected on recent runs (check this to spot any US jobs being dropped)
drop view if exists recent_location_rejections;
create view recent_location_rejections with (security_invoker = true) as
select source_id, board_token, started_at, rejected_location, rejected_samples
from collection_runs
where rejected_location > 0
order by started_at desc;
