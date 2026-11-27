-- MANUAL maintenance. Nothing here runs automatically. Run ONE block at a time in Supabase -> SQL Editor.

-- 1) How much space is used? (free limit is 500 MB)
select pg_size_pretty(pg_database_size(current_database())) as total_database;
select * from storage_usage;

-- 2) PREVIEW what a cleanup would remove (change 30 to any number of days)
select count(*) as closed_jobs_older_than_30d from jobs where status = 'closed' and closed_at < now() - interval '30 days';
select count(*) as run_logs_older_than_14d from collection_runs where started_at < now() - interval '14 days';

-- 3) DELETE closed jobs (listings that no longer exist or no longer match). Safe: they are not shown on the board.
--    Note: possible_repost detection can only see closed jobs that still exist.
delete from jobs where status = 'closed' and closed_at < now() - interval '30 days';

-- 4) DELETE old run summaries
delete from collection_runs where started_at < now() - interval '14 days';

-- 5) Bigger cleanup: ALL closed jobs, any age
-- delete from jobs where status = 'closed';

-- 6) Remove active jobs posted more than 60 days ago (normally none: the 21-day limit already closes them).
--    If the collector still sees them and they match your filters, they come back as new rows.
-- delete from jobs where status = 'active' and posted_at < now() - interval '60 days';

-- 7) If the size shown does not drop after a delete, reclaim the space. Run this line ALONE:
-- vacuum full jobs;
