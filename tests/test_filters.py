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
