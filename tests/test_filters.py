import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'collector'))
from filters import *

P = {'id': 1, 'titles': ['Software Engineer', 'Frontend Engineer', 'SDE', 'Backend Engineer', 'Full Stack Engineer'],
     'exclude_keywords': ['sales', 'qa', 'manager'], 'include_keywords': [], 'states': [],
     'workplace_types': [], 'experience_levels': [], 'include_unclear_location': False}


def job(title, loc):
    j = {'title': title, 'location': loc, 'description': '', 'company': 'X'}
    j.update(parse_location(loc, title))
    j['experience_level'] = infer_experience(title)
    return j


def m(title, loc, **over):
    return bool(match_profiles(job(title, loc), [{**P, **over}]))


def test_title_variants():
    assert m('Senior Software Engineer, Payments', 'San Francisco, CA')
    assert m('Front-End Engineer', 'Austin, TX')
    assert m('Software Development Engineer II', 'Seattle, WA')
    assert m('Back End Engineer', 'New York, NY')


def test_excludes_and_unrelated():
    assert not m('Sales Engineer', 'Austin, TX')
    assert not m('Engineering Manager, Software Engineer', 'Austin, TX')
    assert not m('Recruiter', 'Austin, TX')
    assert not m('QA Software Engineer', 'Austin, TX')


def test_location():
    assert m('Software Engineer', 'Remote - US')
    assert m('Software Engineer', 'New York, New York')
    assert not m('Software Engineer', 'London, United Kingdom')
    assert not m('Software Engineer', 'Toronto, Canada')
    assert not m('Software Engineer', 'Remote')
    assert m('Software Engineer', 'Remote', include_unclear_location=True)
    assert not m('Software Engineer', 'Remote - Germany', include_unclear_location=True)


def test_state_filter():
    assert m('Software Engineer', 'Austin, TX', states=['TX'])
    assert not m('Software Engineer', 'Austin, TX', states=['CA'])
    assert m('Software Engineer', 'Remote - US', states=['CA'])


def test_workplace_and_level():
    assert job('Software Engineer', 'Remote - US')['workplace_type'] == 'remote'
    assert job('Software Engineer', 'Hybrid - Austin, TX')['workplace_type'] == 'hybrid'
    assert job('Software Engineer', 'Austin, TX')['workplace_type'] == 'unspecified'
    assert infer_experience('Senior Software Engineer') == 'senior'
    assert infer_experience('Software Engineer Intern') == 'internship'
    assert not m('Senior Software Engineer', 'Austin, TX', experience_levels=['entry'])


def test_fingerprint_stable():
    assert fingerprint('Stripe', 'Software Engineer', 'Austin, TX') == fingerprint('stripe ', 'Software  Engineer', 'austin, tx')


def test_max_age():
    from datetime import datetime, timedelta, timezone
    old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    new = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    j = job('Software Engineer', 'Austin, TX')
    assert not match_profiles({**j, 'posted_at': old}, [{**P, 'max_age_days': 14}])
    assert match_profiles({**j, 'posted_at': new}, [{**P, 'max_age_days': 14}])
    assert match_profiles({**j, 'posted_at': None}, [{**P, 'max_age_days': 14}])   # unknown date kept
    assert match_profiles({**j, 'posted_at': old}, [{**P, 'max_age_days': None}])  # no limit set
    assert is_older_than('2019-11-14T22:28:57-05:00', 14)


def loc(l):
    r = parse_location(l)
    return r['country'], r['state'], r['confidence'], r['foreign']


def test_city_only_and_state_forms():
    assert loc('Seattle')[:3] == ('US', 'WA', 'city')
    assert loc('San Francisco')[:3] == ('US', 'CA', 'city')
    assert loc('San Francisco CA')[:2] == ('US', 'CA')          # no comma
    assert loc('Washington, DC')[:2] == ('US', 'DC')
    assert loc('New Mexico')[:2] == ('US', 'NM')
    assert loc('Morgantown, West Virginia')[:2] == ('US', 'WV')  # not Virginia
    assert loc('Atlanta, Georgia')[:2] == ('US', 'GA')
    assert loc('Fishers, IN')[:3] == ('US', 'IN', 'state')       # Indiana, no foreign signal
    assert loc('Paris, TX')[0] == 'US'                           # unambiguous code beats foreign-sounding city
    assert loc('Portland')[:2] == ('US', None)                   # two possible states -> none claimed


def test_foreign_not_mistaken_for_us():
    for l in ['Bengaluru, IN', 'Toronto, CA', 'Berlin, DE', 'Tbilisi, Georgia', 'London, United Kingdom',
              'Paris', 'San Jose, Costa Rica', 'Sao Paulo, SP', 'Zürich', 'Remote - Germany', 'Tel Aviv, IL']:
        assert loc(l)[0] is None, l
        assert loc(l)[3] is True, l


def test_unclear_stays_unclear():
    assert loc('Remote')[0] is None and loc('Remote')[3] is False
    assert loc('Remote - North America')[0] is None and loc('Remote - North America')[3] is False


def test_ignore_location_flag():
    j = job('Software Engineer', 'London, United Kingdom')
    assert not match_profiles(j, [P])
    assert match_profiles(j, [P], ignore_location=True)
    assert not match_profiles(job('Recruiter', 'London, United Kingdom'), [P], ignore_location=True)


def test_city_only_job_is_collected():
    assert m('Software Engineer', 'Seattle')
    assert m('Software Engineer', 'Seattle', states=['WA'])
    assert not m('Software Engineer', 'Seattle', states=['TX'])
    assert not m('Software Engineer', 'Bengaluru, IN')
    assert m('Software Engineer', 'Remote - North America', include_unclear_location=True)
    assert not m('Software Engineer', 'Bengaluru, IN', include_unclear_location=True)


def test_unlisted_countries_and_provinces_blocked():
    for l in ['Remote - Estonia', 'Ontario', 'Remote - Latvia', 'Remote - Lithuania', 'Bulgaria', 'Remote - Peru',
              'Quebec', 'British Columbia', 'Karnataka', 'Remote - Morocco']:
        assert loc(l)[0] is None and loc(l)[3] is True, l
    assert not m('Software Engineer', 'Remote - Estonia', include_unclear_location=True)
    assert not m('Software Engineer', 'Ontario', include_unclear_location=True)
    assert m('Software Engineer', 'San Juan, Puerto Rico', include_unclear_location=True)   # US territory still allowed
    assert m('Software Engineer', 'Lebanon, NH')                                            # US town, unambiguous state
    assert m('Software Engineer', 'Hybrid', include_unclear_location=True)
