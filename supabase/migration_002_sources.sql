-- Phase 2. Run once in Supabase -> SQL Editor. Safe to re-run.

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
