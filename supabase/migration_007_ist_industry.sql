-- Phase 6: IST times, company industry, storage tools. Run once in Supabase -> SQL Editor. Safe to re-run.

alter table company_boards add column if not exists industry text;     -- you or I fill this in; never touched by the collector

-- latest_jobs: adds posted_ist, first_seen_ist and industry at the end (original UTC columns are kept)
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
  b.salary_min, b.salary_max, b.salary_currency, b.salary_period, b.salary_source,
  to_char(b.posted_at at time zone 'Asia/Kolkata', 'DD Mon YYYY, HH12:MI AM') || ' IST' as posted_ist,
  to_char(b.first_detected_at at time zone 'Asia/Kolkata', 'DD Mon YYYY, HH12:MI AM') || ' IST' as first_seen_ist,
  coalesce(cb.industry, 'Unknown') as industry
from base b
cross join cut c
left join company_boards cb on cb.source_id = b.source_id and cb.board_token = b.board_token
left join lateral (
  select min(o.first_detected_at) as earlier_seen
  from jobs o
  where o.fingerprint = b.fingerprint and o.id <> b.id and o.status = 'closed'
    and o.first_detected_at < b.first_detected_at
) r on true
order by b.first_detected_at desc, b.effective_at desc;



drop view if exists board_health;
create view board_health with (security_invoker = true) as
select source_id, company_name, board_token, enabled, industry, last_error, disabled_reason, consecutive_failures,
       to_char(last_checked_at at time zone 'Asia/Kolkata', 'DD Mon YYYY, HH12:MI AM') || ' IST' as last_checked_ist,
       to_char(last_success_at at time zone 'Asia/Kolkata', 'DD Mon YYYY, HH12:MI AM') || ' IST' as last_success_ist
from company_boards
order by (last_error is null), source_id, company_name;

drop view if exists recent_runs;
create view recent_runs with (security_invoker = true) as
select to_char(started_at at time zone 'Asia/Kolkata', 'DD Mon YYYY, HH12:MI AM') || ' IST' as started_ist, duration_s, boards_ok, boards_failed, boards_skipped,
       boards_disabled, inserted, updated, closed, detail_fetches, error
from collection_runs where source_id = 'all' order by started_at desc limit 50;

drop view if exists recent_location_rejections;
create view recent_location_rejections with (security_invoker = true) as
select to_char(started_at at time zone 'Asia/Kolkata', 'DD Mon YYYY, HH12:MI AM') || ' IST' as started_ist, rejected_location, rejected_samples
from collection_runs where source_id = 'all' and rejected_location > 0 order by started_at desc;

-- Storage monitor (private: not readable through the public API)
drop view if exists storage_usage;
create view storage_usage as
select relname as table_name, n_live_tup as approx_rows,
       pg_size_pretty(pg_total_relation_size(relid)) as total_size
from pg_stat_user_tables order by pg_total_relation_size(relid) desc;
revoke all on storage_usage from anon, authenticated;
