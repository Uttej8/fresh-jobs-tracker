"""One collection cycle. Run by GitHub Actions on a schedule: python collector/main.py"""
import logging
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from filters import (fingerprint, infer_experience, match_profiles, parse_location)  # noqa: E402
from sources import COLLECTORS  # noqa: E402

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('collector')
now = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731

ROW_KEYS = ('source_id', 'source_job_id', 'board_token', 'title', 'company', 'location', 'city', 'state',
            'country', 'workplace_type', 'employment_type', 'experience_level', 'description', 'application_url', 'posted_at',
            'last_updated_at', 'fingerprint')


def load_profiles(db) -> list[dict]:
    profiles = db.table('profiles').select('*').eq('active', True).execute().data
    for p in profiles:
        rows = db.table('profile_titles').select('title').eq('profile_id', p['id']).eq('enabled', True).execute().data
        p['titles'] = [r['title'] for r in rows]
    return [p for p in profiles if p['titles']]


def enrich(raw: dict, board_token: str, source_id: str) -> dict:
    loc = parse_location(raw['location'], raw['title'])
    if raw.get('workplace_hint'):            # structured data from the source beats text guessing
        loc['workplace_type'] = raw['workplace_hint']
    hint = raw.get('country_hint') or ''
    if hint == 'US':
        loc['country'], loc['foreign'] = 'US', False
    elif hint:
        loc['country'], loc['foreign'] = None, True
    return {**raw, **loc, 'employment_type': raw.get('employment_type') or 'unspecified', 'source_id': source_id, 'board_token': board_token,
            'experience_level': infer_experience(raw['title']),
            'fingerprint': fingerprint(raw['company'], raw['title'], raw['location'])}


def run_board(db, board: dict, profiles: list[dict]):
    source_id, token = board['source_id'], board['board_token']
    run = db.table('collection_runs').insert({'source_id': source_id, 'board_token': token}).execute().data[0]
    stats = dict(fetched=0, matched=0, inserted=0, updated=0, closed=0, error=None)
    try:
        raw_jobs = COLLECTORS[source_id].fetch(token, board['company_name'])
        stats['fetched'] = len(raw_jobs)
        existing = {r['source_job_id']: r for r in db.table('jobs').select('source_job_id,status')
                    .eq('source_id', source_id).eq('board_token', token).execute().data}
        if not raw_jobs and any(r['status'] == 'active' for r in existing.values()):
            # An empty list while we hold active jobs is more likely an API glitch than every job closing.
            raise RuntimeError('Board returned 0 jobs but we hold active ones; kept them (possible API glitch)')
        seen, new_rows, upd_rows = set(), [], []
        for raw in raw_jobs:
            job = enrich(raw, token, source_id)
            ids = match_profiles(job, profiles)
            if not ids:
                continue
            seen.add(job['source_job_id'])
            row = {k: job[k] for k in ROW_KEYS}
            row.update(profile_ids=ids, last_verified_at=now(), status='active', closed_at=None)
            (upd_rows if job['source_job_id'] in existing else new_rows).append(row)
        stats['matched'] = len(seen)
        if new_rows:
            db.table('jobs').insert(new_rows).execute()
        if upd_rows:  # first_detected_at is deliberately absent so it is never overwritten
            db.table('jobs').upsert(upd_rows, on_conflict='source_id,source_job_id').execute()
        stats['inserted'], stats['updated'] = len(new_rows), len(upd_rows)
        # Expiry: only safe because the fetch above succeeded.
        gone = [i for i, r in existing.items() if i not in seen and r['status'] == 'active']
        for i in range(0, len(gone), 100):
            db.table('jobs').update({'status': 'closed', 'closed_at': now()}).eq('source_id', source_id) \
                .eq('board_token', token).in_('source_job_id', gone[i:i + 100]).execute()
        stats['closed'] = len(gone)
        db.table('company_boards').update({'last_checked_at': now(), 'last_success_at': now(),
                                           'last_error': None}).eq('id', board['id']).execute()
        log.info('%s/%s ok %s', source_id, token, stats)
    except Exception as e:  # one bad board must never stop the others
        stats['error'] = f'{type(e).__name__}: {e}'[:500]
        log.error('%s/%s FAILED %s', source_id, token, stats['error'])
        db.table('company_boards').update({'last_checked_at': now(), 'last_error': stats['error']}) \
            .eq('id', board['id']).execute()
    db.table('collection_runs').update({**stats, 'finished_at': now()}).eq('id', run['id']).execute()
    return stats


def main() -> int:
    from supabase import create_client
    db = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
    profiles = load_profiles(db)
    if not profiles:
        log.warning('No active profiles with enabled titles. Nothing to do.')
        return 0
    enabled = {s['id'] for s in db.table('sources').select('id').eq('enabled', True).execute().data}
    boards = [b for b in db.table('company_boards').select('*').eq('enabled', True).execute().data
              if b['source_id'] in enabled and b['source_id'] in COLLECTORS]
    results = [run_board(db, b, profiles) for b in boards]
    for sid in {b['source_id'] for b in boards}:
        ok = any(r['error'] is None for b, r in zip(boards, results) if b['source_id'] == sid)
        db.table('sources').update({'last_checked_at': now(), **({'last_success_at': now()} if ok else {}),
                                    'last_error': None if ok else 'all boards failed'}).eq('id', sid).execute()
    failed = sum(1 for r in results if r['error'])
    log.info('Done: %d boards, %d failed', len(results), failed)
    return 1 if boards and failed == len(boards) else 0  # red X in GitHub only if EVERYTHING failed


if __name__ == '__main__':
    sys.exit(main())
