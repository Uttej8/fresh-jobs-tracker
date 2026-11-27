"""One collection cycle (run by GitHub Actions): python collector/main.py

Design for thousands of boards:
- Boards are fetched in parallel (per-vendor concurrency caps), but ALL database access happens in the main thread.
- Existing jobs are loaded once, so unchanged listings cause no writes. Writes are bulk upserts.
- A time budget stops starting new boards; unfinished boards are picked up first on the next run.
- Dead boards (repeated 404s) and long-failing boards are auto-disabled; one failure never stops the rest.
"""
import logging
import os
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))
import salary as sal  # noqa: E402
from filters import (fingerprint, infer_experience, match_profiles, parse_location)  # noqa: E402
from sources import COLLECTORS  # noqa: E402

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('collector')
now = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731

WORKERS = int(os.environ.get('WORKERS', '16'))
BUDGET_S = float(os.environ.get('RUN_BUDGET_MINUTES', '100')) * 60
DETAIL_CAP = int(os.environ.get('DETAIL_CAP', '40'))        # max per-job detail calls per board per run
LIMITS = {'greenhouse': 8, 'lever': 4, 'ashby': 6, 'workable': 2}
SEMS = {k: threading.Semaphore(v) for k, v in LIMITS.items()}
MAX_GONE_FAILS, MAX_OTHER_FAILS = 3, 12                      # 404/410 vs any other error, consecutive runs

ROW_KEYS = ('source_id', 'source_job_id', 'board_token', 'title', 'company', 'location', 'city', 'state', 'country',
            'location_confidence', 'workplace_type', 'employment_type', 'experience_level', 'application_url',
            'posted_at', 'last_updated_at', 'fingerprint')
SALARY_KEYS = ('salary_min', 'salary_max', 'salary_currency', 'salary_period', 'salary_text', 'salary_source')
EXISTING_COLS = ('id,source_id,board_token,source_job_id,status,title,location,application_url,posted_at,profile_ids,'
                 + ','.join(SALARY_KEYS) + ',salary_checked')


def load_profiles(db) -> list[dict]:
    profiles = db.table('profiles').select('*').eq('active', True).execute().data
    for p in profiles:
        rows = db.table('profile_titles').select('title').eq('profile_id', p['id']).eq('enabled', True).execute().data
        p['titles'] = [r['title'] for r in rows]
    return [p for p in profiles if p['titles']]


def enrich(raw: dict, board_token: str, source_id: str) -> dict:
    loc = parse_location(raw['location'], raw['title'])
    loc['location_confidence'] = loc.pop('confidence')
    if raw.get('workplace_hint'):            # structured data from the source beats text guessing
        loc['workplace_type'] = raw['workplace_hint']
    hint = raw.get('country_hint') or ''
    if hint == 'US':
        loc['country'], loc['foreign'], loc['location_confidence'] = 'US', False, 'explicit'
    elif hint:
        loc['country'], loc['foreign'] = None, True
    return {**raw, **loc, 'employment_type': raw.get('employment_type') or 'unspecified',
            'source_id': source_id, 'board_token': board_token,
            'experience_level': infer_experience(raw['title']),
            'fingerprint': fingerprint(raw['company'], raw['title'], raw['location'])}


def build_row(job: dict, ids: list[int], ex: dict | None) -> dict:
    row = {k: job[k] for k in ROW_KEYS}
    if not row.get('posted_at') and ex:
        row['posted_at'] = ex.get('posted_at')
    row.update(profile_ids=ids, last_verified_at=now(), status='active', closed_at=None)
    if job.get('salary_checked'):
        s = job.get('salary') or {}
        row.update({k: s.get(k) for k in SALARY_KEYS}, salary_checked=True)
    elif ex:                                  # keep what we already know; do not overwrite with blanks
        row.update({k: ex.get(k) for k in SALARY_KEYS}, salary_checked=bool(ex.get('salary_checked')))
    else:
        row.update({k: None for k in SALARY_KEYS}, salary_checked=False)
    return row


def changed(row: dict, ex: dict) -> bool:
    return (ex['status'] != 'active' or row['title'] != ex['title'] or (row['location'] or '') != (ex['location'] or '')
            or row['application_url'] != ex['application_url']
            or sorted(row['profile_ids']) != sorted(ex.get('profile_ids') or [])
            or row['salary_checked'] != bool(ex.get('salary_checked'))
            or (row['salary_text'] or None) != (ex.get('salary_text') or None))


def process_board(board: dict, profiles: list[dict], existing: dict, deadline: float) -> dict:
    """Runs in a worker thread. Network + filtering only, NO database access."""
    res = dict(board=board, rows=[], close_ids=[], fetched=0, matched=0, inserted=0, updated=0, details=0,
               rejected=[], error=None, status=None, skipped=False)
    if time.monotonic() > deadline:
        res['skipped'] = True
        return res
    sid, token = board['source_id'], board['board_token']
    col, sem = COLLECTORS[sid], SEMS.get(sid) or threading.Semaphore(4)
    try:
        with sem:
            raws = col.fetch(token, board['company_name'])
        res['fetched'] = len(raws)
        if not raws and any(e['status'] == 'active' for e in existing.values()):
            raise RuntimeError('Board returned 0 jobs but we hold active ones; kept them (possible API glitch)')
        cands = []
        for raw in raws:
            job = enrich(raw, token, sid)
            ex = existing.get(job['source_job_id'])
            if ex and not job.get('posted_at'):
                job['posted_at'] = ex.get('posted_at')
            ids = match_profiles(job, profiles)
            if ids:
                cands.append((job, ids))
            elif match_profiles(job, profiles, ignore_location=True):    # would match, but location said no
                res['rejected'].append(job['location'] or '(blank)')
        final, used = [], 0
        for job, ids in cands:
            ex = existing.get(job['source_job_id'])
            if (hasattr(col, 'detail') and (ex is None or not ex.get('salary_checked'))
                    and used < DETAIL_CAP and time.monotonic() < deadline):
                try:
                    with sem:
                        d = col.detail(token, job['source_job_id'])
                    used += 1
                    if d.get('posted_at') and not job.get('posted_at'):
                        job['posted_at'] = d['posted_at']
                    job['salary'] = d.get('salary') or sal.extract(d.get('text'))
                    job['salary_checked'] = True
                    ids = match_profiles(job, profiles)       # real posting date may now fail the age limit
                except Exception as e:                        # detail failure never loses the job
                    log.debug('detail failed %s/%s: %s', token, job['source_job_id'], e)
            final.append((job, ids))
        res['details'] = used
        seen = set()
        for job, ids in final:
            if not ids:
                continue
            jid = job['source_job_id']
            seen.add(jid)
            ex = existing.get(jid)
            row = build_row(job, ids, ex)
            if ex is None:
                res['inserted'] += 1
                res['rows'].append(row)
            elif changed(row, ex):
                res['updated'] += 1
                res['rows'].append(row)
        res['matched'] = len(seen)
        res['close_ids'] = [e['id'] for jid, e in existing.items() if jid not in seen and e['status'] == 'active']
    except Exception as e:
        res.update(rows=[], close_ids=[], inserted=0, updated=0, matched=0,
                   error=f'{type(e).__name__}: {e}'[:300],
                   status=getattr(getattr(e, 'response', None), 'status_code', None))
    return res


def fetch_all(db, table: str, columns: str = '*', **eq):
    out, start = [], 0
    while True:
        q = db.table(table).select(columns)
        for k, v in eq.items():
            q = q.eq(k, v)
        page = q.order('id').range(start, start + 999).execute().data
        out += page
        if len(page) < 1000:
            return out
        start += 1000


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def main() -> int:
    from supabase import create_client
    t0 = time.monotonic()
    started = now()
    db = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
    profiles = load_profiles(db)
    if not profiles:
        log.warning('No active profiles with enabled titles. Nothing to do.')
        return 0
    enabled = {s['id'] for s in db.table('sources').select('id').eq('enabled', True).execute().data}
    boards = [b for b in fetch_all(db, 'company_boards', enabled=True)
              if b['source_id'] in enabled and b['source_id'] in COLLECTORS]
    boards.sort(key=lambda b: b.get('last_checked_at') or '')        # least recently checked first
    existing: dict = {}
    for r in fetch_all(db, 'jobs', EXISTING_COLS):
        existing.setdefault((r['source_id'], r['board_token']), {})[r['source_job_id']] = r
    log.info('%d boards, %d existing jobs, %d profile(s)', len(boards), sum(map(len, existing.values())), len(profiles))

    deadline = t0 + BUDGET_S
    tot = Counter()
    errors, rejected = Counter(), set()
    ok_rows, fail_rows, off_rows, job_buf, close_buf = [], [], [], [], []

    def flush(force=False):
        if len(job_buf) >= 500 or (force and job_buf):
            uniq = list({(r['source_id'], r['source_job_id']): r for r in job_buf}.values())  # no duplicate keys per call
            for c in chunks(uniq, 500):
                db.table('jobs').upsert(c, on_conflict='source_id,source_job_id').execute()
            job_buf.clear()
        if len(close_buf) >= 400 or (force and close_buf):
            for c in chunks(close_buf, 200):
                db.table('jobs').update({'status': 'closed', 'closed_at': now()}).in_('id', c).execute()
            close_buf.clear()
        if force:
            for rows in (ok_rows, fail_rows, off_rows):
                for c in chunks(rows, 500):
                    db.table('company_boards').upsert(c, on_conflict='source_id,board_token').execute()
                rows.clear()

    with ThreadPoolExecutor(WORKERS) as pool:
        futs = [pool.submit(process_board, b, profiles, existing.get((b['source_id'], b['board_token']), {}), deadline)
                for b in boards]
        for f in as_completed(futs):
            r = f.result()
            b = r['board']
            if r['skipped']:
                tot['skipped'] += 1
                continue
            base = {'source_id': b['source_id'], 'board_token': b['board_token'],     # no id: it is GENERATED ALWAYS
                    'company_name': b['company_name'], 'last_checked_at': now()}
            if r['error']:
                tot['failed'] += 1
                errors[r['error'].split(':')[0] + (f" {r['status']}" if r['status'] else '')] += 1
                # 429 = "slow down", not "dead": it must never count toward auto-disable
                fails = (b.get('consecutive_failures') or 0) + (0 if r['status'] == 429 else 1)
                limit = MAX_GONE_FAILS if r['status'] in (404, 410) else MAX_OTHER_FAILS
                row = {**base, 'last_error': r['error'], 'consecutive_failures': fails}
                if fails >= limit:
                    off_rows.append({**row, 'enabled': False, 'disabled_reason': f"auto-disabled: {r['error']}"})
                    tot['disabled'] += 1
                else:
                    fail_rows.append(row)
                if tot['failed'] <= 15:
                    log.warning('%s/%s FAILED %s', b['source_id'], b['board_token'], r['error'])
                continue
            tot['ok'] += 1
            for k in ('fetched', 'matched', 'inserted', 'updated', 'details'):
                tot[k] += r[k]
            tot['closed'] += len(r['close_ids'])
            tot['rejected'] += len(r['rejected'])
            rejected.update(r['rejected'])
            job_buf.extend(r['rows'])
            close_buf.extend(r['close_ids'])
            ok_rows.append({**base, 'last_success_at': now(), 'last_error': None, 'consecutive_failures': 0,
                            'last_fetched_count': r['fetched'], 'last_matched_count': r['matched']})
            flush()
    write_failed = False
    try:
        flush(force=True)
    except Exception as e:                       # keep going so the run summary is still recorded
        write_failed = True
        log.error('final database write failed: %s', e)

    dur = round(time.monotonic() - t0, 1)
    summary = '; '.join(f'{k} x{v}' for k, v in errors.most_common(5)) or None
    db.table('collection_runs').insert({
        'source_id': 'all', 'started_at': started, 'finished_at': now(), 'fetched': tot['fetched'],
        'matched': tot['matched'], 'inserted': tot['inserted'], 'updated': tot['updated'], 'closed': tot['closed'],
        'error': summary, 'rejected_location': tot['rejected'], 'rejected_samples': sorted(rejected)[:12],
        'boards_ok': tot['ok'], 'boards_failed': tot['failed'], 'boards_skipped': tot['skipped'],
        'boards_disabled': tot['disabled'], 'detail_fetches': tot['details'], 'duration_s': dur}).execute()
    if os.environ.get('HOUSEKEEPING', 'off').lower() == 'on':     # automatic deletion is OFF by default
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            db.table('jobs').delete().eq('status', 'closed').lt('closed_at', cutoff).execute()
            db.table('collection_runs').delete().lt(
                'started_at', (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()).execute()
        except Exception as e:
            log.warning('housekeeping failed: %s', e)
    log.info('DONE in %.0fs: ok=%d failed=%d skipped=%d disabled=%d | fetched=%d matched=%d new=%d updated=%d '
             'closed=%d details=%d | errors: %s', dur, tot['ok'], tot['failed'], tot['skipped'], tot['disabled'],
             tot['fetched'], tot['matched'], tot['inserted'], tot['updated'], tot['closed'], tot['details'], summary)
    return 1 if write_failed or (boards and tot['ok'] == 0 and tot['failed']) else 0


if __name__ == '__main__':
    sys.exit(main())
