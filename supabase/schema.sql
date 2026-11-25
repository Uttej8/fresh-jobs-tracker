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
