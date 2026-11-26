-- Phase 5: scale + salary. Run once in Supabase -> SQL Editor, BEFORE uploading the new code. Safe to re-run.

-- Board health tracking (auto-disable of dead boards)
alter table company_boards add column if not exists consecutive_failures int not null default 0;
alter table company_boards add column if not exists last_fetched_count int;
alter table company_boards add column if not exists last_matched_count int;
alter table company_boards add column if not exists disabled_reason text;

-- Salary (NULL means "not listed"; the view shows the words 'Not listed')
alter table jobs add column if not exists salary_min numeric;
alter table jobs add column if not exists salary_max numeric;
alter table jobs add column if not exists salary_currency text;
alter table jobs add column if not exists salary_period text;
alter table jobs add column if not exists salary_text text;
alter table jobs add column if not exists salary_source text;       -- 'structured' (vendor field) or 'description'
alter table jobs add column if not exists salary_checked boolean not null default false;

-- One summary row per collection run (instead of one per company)
alter table collection_runs add column if not exists boards_ok int;
alter table collection_runs add column if not exists boards_failed int;
alter table collection_runs add column if not exists boards_skipped int;
alter table collection_runs add column if not exists boards_disabled int;
alter table collection_runs add column if not exists detail_fetches int;
alter table collection_runs add column if not exists duration_s real;

-- Descriptions are no longer stored (saves space). Clear the old ones.
update jobs set description = null where description is not null;
create index if not exists jobs_closed_at on jobs (closed_at) where status = 'closed';

-- latest_jobs, now with salary columns at the end.
-- NOTE: if you already ran migration_005_public_read.sql, run it again after this (recreating a view resets it).
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
  b.location_confidence,
  coalesce(b.salary_text, 'Not listed') as salary,
  b.salary_min, b.salary_max, b.salary_currency, b.salary_period, b.salary_source
from base b
cross join cut c
left join lateral (
  select min(o.first_detected_at) as earlier_seen
  from jobs o
  where o.fingerprint = b.fingerprint and o.id <> b.id and o.status = 'closed'
    and o.first_detected_at < b.first_detected_at
) r on true
order by b.first_detected_at desc, b.effective_at desc;


-- Per-batch overview: how many boards are enabled, healthy, dead
drop view if exists board_overview;
create view board_overview with (security_invoker = true) as
select source_id,
       count(*) as boards,
       count(*) filter (where enabled) as enabled,
       count(*) filter (where not enabled and disabled_reason is not null) as auto_disabled,
       count(*) filter (where enabled and last_error is not null) as failing
from company_boards group by source_id order by source_id;
