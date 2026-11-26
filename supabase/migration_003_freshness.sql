-- Phase 3: freshness labels, cross-source dedupe, repost detection. Run once in Supabase -> SQL Editor.
-- Safe to re-run. Labels are computed live when you open the view, so they never go stale.

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
