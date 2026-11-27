# Fresh Jobs Tracker (collector scaled for thousands of boards, salary column)

**Purpose:** find fresh US software jobs to apply to during an India evening session
(about 5:30 PM to 2 AM IST). Collection only runs in that window.

**Status:** code written, offline logic tested. Live collection is NOT yet verified.
It is verified the first time you run the workflow (step 6) and see rows in Supabase.

## Schedule (IST window)
GitHub cron is in UTC (IST = UTC + 5:30). The workflow runs at minute 5 of hours 12-20 UTC:

| IST time | UTC time |
|---|---|
| 5:35 PM | 12:05 |
| 6:35 PM | 13:05 |
| 7:35 PM | 14:05 |
| 8:35 PM | 15:05 |
| 9:35 PM | 16:05 |
| 10:35 PM | 17:05 |
| 11:35 PM | 18:05 |
| 12:35 AM | 19:05 |
| 1:35 AM | 20:05 |

- The 5:35 PM run catches everything posted during the day, so you start with a full list.
- GitHub can delay scheduled runs by 5-20 minutes, so treat times as approximate.
- Need a refresh outside the window? Actions -> "Collect jobs" -> Run workflow.
- To change the window, edit the `cron` line in `.github/workflows/collect.yml`
  (convert IST to UTC by subtracting 5:30).
- Jobs are only marked "closed" during these runs, so listings that vanished after 1:35 AM show as
  closed at the next 5:35 PM run.

## Architecture
GitHub Actions (cron) -> `collector/main.py` -> Supabase Postgres <- Next.js site on Vercel (Phases 4 and 5)
- Config (profiles, titles, keywords, company boards) lives in the DB. Editing it needs no redeploy
  and nothing resets on restart.
- Each company board is fetched in its own try/except, so one failure never stops the others.
- `posted_at` is filled only when the source supplies it. Otherwise the UI shows "First detected".

## Setup (about 15 minutes, $0)
1. Create a free account at supabase.com, then New project (save the DB password).
2. Supabase -> SQL Editor -> paste all of `supabase/schema.sql` -> Run.
3. Supabase -> Project Settings -> API: copy the **Project URL** and the **service_role** key (keep it secret).
4. Create a GitHub repo and push this folder to it.
5. GitHub repo -> Settings -> Secrets and variables -> Actions -> New repository secret:
   `SUPABASE_URL` and `SUPABASE_SERVICE_KEY`.
6. GitHub repo -> Actions -> "Collect jobs" -> Run workflow. Wait about a minute.
7. Check Supabase -> Table Editor: `jobs` (rows) and `collection_runs` (errors per company).

## Test the logic locally (no network or DB needed)
    pip install pytest
    python3 -m pytest tests

## Change what it searches (until the Admin UI exists in Phase 5)
Supabase -> Table Editor:
- `profile_titles`: add, edit or disable job titles.
- `profiles`: keywords, excluded keywords, states, experience levels.
- `company_boards`: add a company (source `greenhouse`, token = the part in boards.greenhouse.io/TOKEN).
Changes apply on the next run.

## Sources
Greenhouse (verified live), Lever, Ashby, Workable (written from the public API docs, **verify on first run**).
Open the `board_health` view to see which companies work and which show an error.
Add a company: `company_boards` -> source_id (greenhouse / lever / ashby / workable) + board_token
(the last part of its jobs URL, e.g. jobs.lever.co/**plaid**).
Updating an existing database: run `supabase/migration_002_sources.sql` once.

## Known limits
- Seed company tokens are unverified examples. Bad tokens show in `board_health`.
- Lever EU-hosted accounts (api.eu.lever.co) are not supported yet.
- Workable's public endpoint is the least documented; expect it to be the first to need a tweak.
- If a board returns 0 jobs while we hold active ones, the collector keeps them and flags an error
  (assumed API glitch). Disable the board if the company really has no openings.
- Workplace type is `unspecified` unless the text says remote or hybrid. It is not guessed.
- Cross-source dedupe stores a `fingerprint`; the merge logic is Phase 3.
- GitHub disables scheduled workflows on a repo with no activity for 60 days. If that happens,
  re-enable it in the Actions tab or push any small commit.
- Free Supabase pauses projects after about 1 week with no activity. Daily runs prevent this.
- GitHub Actions is free for public repos. Private repos get 2,000 min/month; this uses roughly 300.

## Phase 3: reading `latest_jobs`
Open the `latest_jobs` view (all active jobs, newly detected first). Columns:
- `freshness`: last_3h / last_24h / last_3d / last_7d / older.
- `freshness_label`: "Posted 2h ago" when the source gave a real posting date, otherwise "First seen 2h ago".
  "First seen" only means when WE first noticed it, so it can overstate freshness for jobs that were
  already open when tracking began.
- `new_this_session`: true if first detected after your last session ended (2:00 AM IST).
- `possible_repost`: an older, now-closed copy with the same company, title and location exists.
  It may be the same role re-listed to look new.
- Duplicates: the same company+title+location found on two different sources is shown once.
  Identical postings on the SAME source are kept, because they can be separate openings.
Max age is 21 days (`profiles.max_age_days`).

## Location detection (Phase 3.5)
`location_confidence` in `latest_jobs` tells you how a job was judged to be in the US:
- `explicit`: says US/USA/United States, or has an unambiguous state (TX, NY, "Texas"...).
- `state`: has a code that is also a country code (CA, IN, DE...) and nothing foreign appears with it.
- `city`: only a known US city was given ("Seattle"); the state is filled in from the city.
- `unclear`: no location evidence, e.g. a bare "Remote". Only kept if `profiles.include_unclear_location = true`.
Foreign cities and countries always block a job, so "Bengaluru, IN" is not Indiana and "Toronto, CA" is not California.
The US city list lives in `collector/filters.py` (US_CITIES); add cities there if you see US jobs being missed.
Check `recent_location_rejections` after a run to see which locations were dropped.

## Scale + salary (Phase 5)
- Boards run in parallel (per-vendor caps: Greenhouse 8, Ashby 6, Lever 4). Only the main thread touches the database.
- Existing jobs are loaded once; unchanged jobs cause NO writes. Writes are bulk upserts.
- `RUN_BUDGET_MINUTES` (workflow env, default 100) stops starting new boards; skipped boards are checked first next run.
- Greenhouse is two-step: cheap job list for every board, then a per-job detail call (max 40 per board per run) only for
  jobs that passed your filters and have not been salary-checked. Lever/Ashby return salary in the list.
- Descriptions are NOT stored. They are read in memory to find a salary, then dropped.
  Consequence: `profiles.include_keywords` only sees the title for Greenhouse jobs.
- Dead boards: 3 consecutive 404/410 results, or 12 consecutive other errors, auto-disables the board
  (`company_boards.disabled_reason`). Re-enable by setting `enabled = true` and `consecutive_failures = 0`.
- `collection_runs` now has ONE summary row per run. Per-company status is on `company_boards`.
- Nothing is deleted automatically. Use `supabase/maintenance.sql` by hand. (Set env `HOUSEKEEPING: 'on'` in the workflow
  if you ever want the old automatic cleanup of closed jobs >30 days and run logs >14 days.)
- Salary: `latest_jobs.salary` shows the range or the words "Not listed". Source is `structured` (vendor field) or
  `description` (an explicit range found in the posting text). Nothing is ever estimated.

## Enabling companies in batches
Companies imported from the directory are disabled and numbered `batch` 1..20 (500 each).
    update company_boards set enabled = true where batch = 1;          -- first 500
    update company_boards set enabled = true where batch <= 3;         -- first 1,500
Check `board_overview` and the latest row of `collection_runs` (duration_s, boards_failed) after each step.

## Schedule, times, industry
- Workflow runs hourly 5:40 PM to 12:40 AM IST, Monday to Friday (cron `10 12-19 * * 1-5`, UTC).
- Supabase stores times in UTC. The views `latest_jobs`, `board_health`, `recent_runs` add IST text columns
  (`posted_ist`, `first_seen_ist`, `last_checked_ist`, `started_ist`).
- `company_boards.industry` is filled manually (the vendors do not provide it). `latest_jobs.industry` shows 'Unknown' until set.
