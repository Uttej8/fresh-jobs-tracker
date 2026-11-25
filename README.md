# Fresh Jobs Tracker (Phase 1: foundation + Greenhouse collector)

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

## Known limits (Phase 1)
- Only Greenhouse. Lever, Ashby and Workable come in Phase 2.
- Seed company tokens are unverified examples. Bad tokens show in `company_boards.last_error`.
- Workplace type is `unspecified` unless the text says remote or hybrid. It is not guessed.
- Cross-source dedupe stores a `fingerprint`; the merge logic is Phase 3.
- GitHub disables scheduled workflows on a repo with no activity for 60 days. If that happens,
  re-enable it in the Actions tab or push any small commit.
- Free Supabase pauses projects after about 1 week with no activity. Daily runs prevent this.
- GitHub Actions is free for public repos. Private repos get 2,000 min/month; this uses roughly 300.
