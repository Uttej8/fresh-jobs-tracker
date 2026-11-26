-- Run once in Supabase -> SQL Editor (for databases created before this change)
alter table profiles add column if not exists max_age_days int default 14;
update profiles set max_age_days = 14 where max_age_days is null;
