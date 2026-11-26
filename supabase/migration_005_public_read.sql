-- Phase 4: let the public website read latest_jobs. Run once in Supabase -> SQL Editor.
-- The view only ever returns ACTIVE jobs. Running it with owner rights lets the possible_repost flag
-- see closed twins, which anonymous visitors cannot read directly.
alter view latest_jobs set (security_invoker = false);
grant select on latest_jobs to anon;
