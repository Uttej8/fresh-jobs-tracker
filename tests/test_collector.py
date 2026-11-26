import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'collector'))
import salary as sal
import main
from sources.greenhouse import GreenhouseCollector
from sources.lever import LeverCollector
from sources.ashby import AshbyCollector


def test_salary_text():
    assert sal.extract('Base salary: $120,000 - $150,000 per year')['salary_text'] == '$120,000 - $150,000 / year'
    r = sal.extract('The range is $120k - $150k annually')
    assert (r['salary_min'], r['salary_max'], r['salary_period']) == (120000, 150000, 'year')
    r = sal.extract('Pay: $55 - $70 per hour')
    assert (r['salary_min'], r['salary_max'], r['salary_period']) == (55, 70, 'hour')
    r = sal.extract('California: $140,000 – $180,000. Other US: $120,000 – $150,000')
    assert (r['salary_min'], r['salary_max']) == (120000, 180000) and '|' in r['salary_text']
    assert sal.extract('Salary CAD $90,000 - $110,000')['salary_currency'] == 'CAD'
    assert sal.extract('£60,000 - £80,000')['salary_currency'] == 'GBP'


def test_salary_false_positives_and_none():
    assert sal.extract('We raised $100 - $200 million in funding') is None
    assert sal.extract('Over $10M in revenue, up to $50 - $60 million valuation') is None
    assert sal.extract('Competitive salary and great equity') is None
    assert sal.extract('') is None and sal.extract(None) is None
    assert sal.extract('Bonus of $5,000 - $90,000') is None          # ratio too wide to be a pay range
    assert sal.extract('Equity of $50,000 - $80,000') is None        # equity alone is not salary


def test_salary_structured():
    assert sal.structured(120000, 150000, 'usd', 'per-year-salary')['salary_text'] == '$120,000 - $150,000 / year'
    assert sal.structured(None, None, 'USD', 'year') is None
    assert sal.structured(90000, None, 'USD', None)['salary_text'] == '$90,000 / year'
    assert sal.structured(40, 55, 'USD', 'per-hour-wage')['salary_period'] == 'hour'


def test_vendor_salary_parsing():
    lever = [{'id': '1', 'text': 'Software Engineer', 'categories': {'location': 'Austin, TX'}, 'hostedUrl': 'u',
              'salaryRange': {'min': 130000, 'max': 170000, 'currency': 'USD', 'interval': 'per-year-salary'}}]
    r = LeverCollector.parse(lever, 'A')[0]
    assert r['salary']['salary_source'] == 'structured' and r['salary_checked']
    ashby = {'jobs': [{'id': '1', 'title': 'SWE', 'location': 'Austin, TX', 'jobUrl': 'u', 'compensation': {
        'summaryComponents': [{'compensationType': 'EquityPercentage', 'minValue': 1, 'maxValue': 2},
                              {'compensationType': 'Salary', 'interval': '1 YEAR', 'currencyCode': 'USD',
                               'minValue': 150000, 'maxValue': 200000}]}}]}
    assert AshbyCollector.parse(ashby, 'A')[0]['salary']['salary_min'] == 150000
    ashby['jobs'][0]['compensation'] = {}
    ashby['jobs'][0]['descriptionPlain'] = 'Pay range $100,000 - $130,000 per year'
    assert AshbyCollector.parse(ashby, 'A')[0]['salary']['salary_source'] == 'description'
    gh = GreenhouseCollector.parse_detail({'first_published': '2026-11-20T10:00:00Z', 'content': '&lt;p&gt;x&lt;/p&gt;',
        'pay_input_ranges': [{'min_cents': 15000000, 'max_cents': 19000000, 'currency_type': 'USD'}]})
    assert gh['salary']['salary_text'] == '$150,000 - $190,000 / year' and gh['posted_at']
    assert GreenhouseCollector.parse({'jobs': [{'id': 7, 'title': 'T', 'absolute_url': 'u'}]}, 'A')[0]['salary_checked'] is False


P = [{'id': 1, 'titles': ['Software Engineer'], 'exclude_keywords': [], 'include_keywords': [], 'states': [],
      'workplace_types': [], 'experience_levels': [], 'employment_types': [], 'include_unclear_location': False,
      'max_age_days': 21}]
BOARD = {'id': 5, 'source_id': 'fake', 'board_token': 't', 'company_name': 'Acme'}
FAR = time.monotonic() + 999


def raw(i, title='Software Engineer', loc='Austin, TX', posted=None, checked=False, salary=None):
    return {'source_job_id': str(i), 'title': title, 'company': 'Acme', 'location': loc, 'description': '',
            'application_url': f'https://x/{i}', 'posted_at': posted, 'last_updated_at': None,
            'salary': salary, 'salary_checked': checked}


class Fake:
    def __init__(self, raws, details=None):
        self.raws, self.details, self.calls = raws, details or {}, 0

    def fetch(self, token, name):
        return self.raws

    def detail(self, token, jid):
        self.calls += 1
        if jid == 'boom':
            raise RuntimeError('x')
        return self.details.get(jid, {'posted_at': None, 'text': '', 'salary': None})


def run(raws, existing=None, details=None, deadline=FAR):
    col = Fake(raws, details)
    main.COLLECTORS['fake'] = col
    return main.process_board(BOARD, P, existing or {}, deadline), col


def ex(i, **kw):
    d = {'id': 100 + i, 'status': 'active', 'title': 'Software Engineer', 'location': 'Austin, TX',
         'application_url': f'https://x/{i}', 'posted_at': None, 'profile_ids': [1], 'salary_checked': True,
         'salary_text': None, **{k: None for k in sal.build(1, 2, 'USD', 'year', 's') if k != 'salary_text'}}
    d.update(kw)
    return d


def test_new_unchanged_changed_gone():
    existing = {'1': ex(1), '2': ex(2), '3': ex(3)}
    res, _ = run([raw(1, checked=True), raw(2, title='Software Engineer II', checked=True),
                  raw(4, checked=True), raw(9, title='Recruiter', checked=True)], existing)
    assert res['inserted'] == 1 and res['updated'] == 1            # job 4 new, job 2 changed, job 1 untouched
    assert {r['source_job_id'] for r in res['rows']} == {'2', '4'}
    assert res['close_ids'] == [103]                               # job 3 disappeared
    assert res['matched'] == 3 and res['error'] is None


def test_empty_board_guard_and_errors():
    res, _ = run([], {'1': ex(1)})
    assert res['error'] and not res['close_ids'] and not res['rows']
    main.COLLECTORS['fake'] = type('Bad', (), {'fetch': lambda s, t, n: 1 / 0})()
    res = main.process_board(BOARD, P, {'1': ex(1)}, FAR)
    assert 'ZeroDivisionError' in res['error'] and not res['close_ids']


def test_greenhouse_two_step_detail_and_age():
    old = '2020-01-01T00:00:00Z'
    sal_ok = sal.structured(100000, 120000, 'USD', 'year')
    res, col = run([raw(1), raw(2), raw('boom')],
                   details={'1': {'posted_at': '2026-11-25T00:00:00Z', 'text': '', 'salary': sal_ok},
                            '2': {'posted_at': old, 'text': '', 'salary': None}})
    by = {r['source_job_id']: r for r in res['rows']}
    assert col.calls == 3 and res['details'] == 2
    assert by['1']['salary_text'] == '$100,000 - $120,000 / year' and by['1']['salary_checked'] is True
    assert '2' not in by                                           # real date was 2020: dropped after detail
    assert by['boom']['salary_checked'] is False                   # detail failed: job kept, retried next run


def test_detail_cap_and_carry_forward():
    main.DETAIL_CAP = 2
    res, col = run([raw(i) for i in range(5)])
    main.DETAIL_CAP = 40
    assert col.calls == 2 and len(res['rows']) == 5
    known = ex(1, salary_text='$1 / year', salary_checked=True, salary_min=1, posted_at='2026-11-20T00:00:00Z')
    res, col = run([raw(1, title='Software Engineer, Platform')], {'1': known})
    assert col.calls == 0                                          # already salary-checked: no detail call
    row = res['rows'][0]
    assert row['salary_text'] == '$1 / year' and row['posted_at'] == '2026-11-20T00:00:00Z'


def test_budget_skip_and_old_posts():
    res, col = run([raw(1)], deadline=time.monotonic() - 1)
    assert res['skipped'] and col.calls == 0
    res, _ = run([raw(1, posted='2020-01-01T00:00:00Z', checked=True)])
    assert res['matched'] == 0                                     # older than 21 days from the list date
