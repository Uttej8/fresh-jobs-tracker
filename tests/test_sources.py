"""Offline tests. NOTE: the sample payloads are written from my understanding of each API's documented
shape, so these prove the parsing logic, NOT that the live APIs match. The live run is the real proof."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'collector'))
from sources.lever import LeverCollector
from sources.ashby import AshbyCollector
from sources.workable import WorkableCollector
from filters import match_profiles, parse_location, infer_experience
from main import enrich

P = {'id': 1, 'titles': ['Software Engineer'], 'exclude_keywords': [], 'include_keywords': [], 'states': [],
     'workplace_types': [], 'experience_levels': [], 'employment_types': [], 'include_unclear_location': False,
     'max_age_days': None}


def matched(raw, src='x'):
    job = enrich(raw, 'tok', src)
    return bool(match_profiles(job, [P])), job


def test_lever():
    data = [{'id': 'abc', 'text': 'Software Engineer', 'categories': {'location': 'Remote', 'commitment': 'Full-time'},
             'createdAt': 1700000000000, 'hostedUrl': 'https://jobs.lever.co/x/abc', 'workplaceType': 'remote',
             'country': 'US', 'descriptionPlain': 'Build things'}]
    raw = LeverCollector.parse(data, 'Acme')[0]
    assert raw['posted_at'].startswith('2023-11-14')
    ok, job = matched(raw)
    assert ok and job['workplace_type'] == 'remote' and job['employment_type'] == 'full_time'  # bare 'Remote' resolved by country
    assert LeverCollector.parse([{**data[0], 'country': 'GB'}], 'Acme')[0]['country_hint'] == 'GB'
    assert not matched(LeverCollector.parse([{**data[0], 'country': 'GB'}], 'Acme')[0])[0]


def test_ashby():
    data = {'jobs': [
        {'id': '1', 'title': 'Software Engineer', 'location': 'San Francisco, CA', 'isListed': True,
         'workplaceType': 'Hybrid', 'publishedAt': '2026-11-20T10:00:00.000+00:00', 'jobUrl': 'https://jobs.ashbyhq.com/x/1',
         'employmentType': 'FullTime', 'descriptionPlain': 'x', 'address': {'postalAddress': {'addressCountry': 'United States'}}},
        {'id': '2', 'title': 'Software Engineer', 'location': 'Austin, TX', 'isListed': False, 'jobUrl': 'u'}]}
    raws = AshbyCollector.parse(data, 'Acme')
    assert len(raws) == 1                       # unlisted skipped
    ok, job = matched(raws[0])
    assert ok and job['workplace_type'] == 'hybrid' and job['employment_type'] == 'full_time'


def test_workable():
    data = {'jobs': [{'shortcode': 'AB12', 'title': 'Software Engineer', 'city': 'Austin', 'state': 'Texas',
                      'country': 'United States', 'published_on': '2026-11-22', 'url': 'https://apply.workable.com/x/j/AB12/',
                      'telecommuting': False, 'employment_type': 'Full-time', 'description': '&lt;p&gt;Hello&lt;/p&gt;'}]}
    raw = WorkableCollector.parse(data, 'Acme')[0]
    assert raw['description'] == 'Hello' and raw['posted_at'] == '2026-11-22'
    ok, job = matched(raw)
    assert ok and job['state'] == 'TX'


def test_bad_payloads_raise():
    for cls, bad in ((LeverCollector, {'ok': False}), (AshbyCollector, []), (WorkableCollector, {'error': 1})):
        try:
            cls.parse(bad, 'A'); assert False
        except ValueError:
            pass


def test_employment_filter():
    raw = LeverCollector.parse([{'id': '1', 'text': 'Software Engineer', 'categories': {'location': 'Austin, TX', 'commitment': 'Contract'},
                                 'hostedUrl': 'u'}], 'A')[0]
    job = enrich(raw, 't', 'lever')
    assert match_profiles(job, [P])
    assert not match_profiles(job, [{**P, 'employment_types': ['full_time']}])
