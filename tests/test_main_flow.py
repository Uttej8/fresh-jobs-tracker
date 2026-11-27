"""Runs main.main() end-to-end against an in-memory fake of the Supabase client (no network)."""
import os, sys, types
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'collector'))
import requests
import main


class Res:
    def __init__(self, data): self.data = data


class Q:
    def __init__(self, db, name): self.db, self.name, self.mode, self.f, self.payload, self.conf = db, name, 'select', [], None, None; self.rng = None
    def select(self, *_): self.mode = 'select'; return self
    def insert(self, rows): self.mode, self.payload = 'insert', rows; return self
    def upsert(self, rows, on_conflict=None): self.mode, self.payload, self.conf = 'upsert', rows, on_conflict; return self
    def update(self, vals): self.mode, self.payload = 'update', vals; return self
    def delete(self): self.mode = 'delete'; return self
    def eq(self, k, v): self.f.append(lambda r: r.get(k) == v); return self
    def lt(self, k, v): self.f.append(lambda r: r.get(k) is not None and r.get(k) < v); return self
    def in_(self, k, vs): self.f.append(lambda r: r.get(k) in vs); return self
    def order(self, *_): return self
    def range(self, a, b): self.rng = (a, b); return self
    def match(self, r): return all(f(r) for f in self.f)
    def execute(self):
        t = self.db.t.setdefault(self.name, [])
        if self.mode == 'select':
            rows = [dict(r) for r in t if self.match(r)]
            return Res(rows[self.rng[0]:self.rng[1] + 1] if self.rng else rows)
        if self.mode in ('insert', 'upsert'):
            rows = self.payload if isinstance(self.payload, list) else [self.payload]
            out = []
            for r in rows:
                if 'id' in r and self.name in ('company_boards', 'jobs', 'collection_runs'):
                    raise AssertionError(f'id is GENERATED ALWAYS on {self.name}: cannot insert/upsert an id')
                keys = (self.conf or '').split(',') if self.mode == 'upsert' else []
                hit = next((x for x in t if keys and all(x.get(k) == r.get(k) for k in keys)), None)
                if hit: hit.update(r); out.append(hit)
                else:
                    new = dict(r); new.setdefault('id', len(t) + 1000); t.append(new); out.append(new)
            return Res(out)
        if self.mode == 'update':
            for r in t:
                if self.match(r): r.update(self.payload)
            return Res([])
        self.db.t[self.name] = [r for r in t if not self.match(r)]
        return Res([])


class DB:
    def __init__(self, t): self.t = t
    def table(self, n): return Q(self, n)


def http_err(code):
    e = requests.HTTPError('boom'); e.response = types.SimpleNamespace(status_code=code); return e


class FakeVendor:
    def fetch(self, token, name):
        if token == 'dead': raise http_err(404)
        if token == 'flaky': raise http_err(503)
        return [{'source_job_id': f'{token}-1', 'title': 'Software Engineer', 'company': name, 'location': 'Austin, TX',
                 'description': '', 'application_url': f'https://x/{token}', 'posted_at': None, 'last_updated_at': None,
                 'salary': None, 'salary_checked': False}]
    def detail(self, token, jid):
        return {'posted_at': '2026-11-25T00:00:00Z', 'text': 'Pay $100,000 - $130,000 per year', 'salary': None}


def test_main_end_to_end():
    boards = [{'id': 1, 'source_id': 'fake', 'board_token': 'good', 'company_name': 'Good', 'enabled': True},
              {'id': 2, 'source_id': 'fake', 'board_token': 'dead', 'company_name': 'Dead', 'enabled': True, 'consecutive_failures': 2},
              {'id': 3, 'source_id': 'fake', 'board_token': 'flaky', 'company_name': 'Flaky', 'enabled': True, 'consecutive_failures': 0}]
    t = {'sources': [{'id': 'fake', 'enabled': True}], 'company_boards': boards,
         'profiles': [{'id': 1, 'active': True, 'exclude_keywords': [], 'include_keywords': [], 'states': [],
                       'workplace_types': [], 'experience_levels': [], 'employment_types': [],
                       'include_unclear_location': False, 'max_age_days': 21}],
         'profile_titles': [{'profile_id': 1, 'title': 'Software Engineer', 'enabled': True}], 'jobs': [], 'collection_runs': []}
    db = DB(t)
    sys.modules['supabase'] = types.SimpleNamespace(create_client=lambda u, k: db)
    os.environ.update(SUPABASE_URL='x', SUPABASE_SERVICE_KEY='y')
    main.COLLECTORS['fake'] = FakeVendor()
    assert main.main() == 0
    jobs = t['jobs']
    assert len(jobs) == 1 and jobs[0]['salary_text'] == '$100,000 - $130,000 / year' and jobs[0]['salary_checked']
    assert 'description' not in jobs[0] and jobs[0]['status'] == 'active'
    by = {b['id']: b for b in t['company_boards']}
    assert by[1]['last_error'] is None and by[1]['consecutive_failures'] == 0 and by[1]['last_matched_count'] == 1
    assert by[2]['enabled'] is False and 'auto-disabled' in by[2]['disabled_reason']      # third 404 in a row
    assert by[3]['enabled'] is True and by[3]['consecutive_failures'] == 1                # 503 only counts, never disables
    run = t['collection_runs'][-1]
    assert run['boards_ok'] == 1 and run['boards_failed'] == 2 and run['boards_disabled'] == 1 and run['inserted'] == 1
    assert main.main() == 0                                                               # second run: nothing changes
    assert len(t['jobs']) == 1 and t['collection_runs'][-1]['inserted'] == 0 and t['collection_runs'][-1]['updated'] == 0
    t['company_boards'][0]['enabled'] = True
    main.COLLECTORS['fake'] = type('Gone', (), {'fetch': lambda s, tok, n: [dict(FakeVendor().fetch('x', 'G')[0], source_job_id='other', title='Software Engineer')] if tok == 'good' else []})()
    main.main()
    assert any(j['status'] == 'closed' for j in t['jobs'])                                # vanished job gets closed


def test_housekeeping_is_opt_in():
    old = {'id': 900, 'source_id': 'fake', 'source_job_id': 'zz', 'board_token': 'gone', 'status': 'closed',
           'closed_at': '2020-01-01T00:00:00+00:00'}
    for flag, expect_left in (('off', 1), ('on', 0)):
        t_ = {'sources': [{'id': 'fake', 'enabled': True}], 'company_boards': [], 'jobs': [dict(old)],
              'profiles': [{'id': 1, 'active': True, 'exclude_keywords': [], 'include_keywords': [], 'states': [],
                            'workplace_types': [], 'experience_levels': [], 'employment_types': [],
                            'include_unclear_location': False, 'max_age_days': 21}],
              'profile_titles': [{'profile_id': 1, 'title': 'Software Engineer', 'enabled': True}], 'collection_runs': []}
        db = DB(t_)
        sys.modules['supabase'] = types.SimpleNamespace(create_client=lambda u, k: db)
        os.environ.update(SUPABASE_URL='x', SUPABASE_SERVICE_KEY='y', HOUSEKEEPING=flag)
        main.main()
        assert len([j for j in t_['jobs'] if j['status'] == 'closed']) == expect_left, flag
    os.environ.pop('HOUSEKEEPING', None)
