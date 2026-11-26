"""Pure-logic job parsing + filtering. No network, no DB: easy to test."""
import hashlib
import re
from datetime import datetime, timedelta, timezone

STATES = {
 'alabama':'AL','alaska':'AK','arizona':'AZ','arkansas':'AR','california':'CA','colorado':'CO','connecticut':'CT',
 'delaware':'DE','florida':'FL','georgia':'GA','hawaii':'HI','idaho':'ID','illinois':'IL','indiana':'IN','iowa':'IA',
 'kansas':'KS','kentucky':'KY','louisiana':'LA','maine':'ME','maryland':'MD','massachusetts':'MA','michigan':'MI',
 'minnesota':'MN','mississippi':'MS','missouri':'MO','montana':'MT','nebraska':'NE','nevada':'NV','new hampshire':'NH',
 'new jersey':'NJ','new mexico':'NM','new york':'NY','north carolina':'NC','north dakota':'ND','ohio':'OH',
 'oklahoma':'OK','oregon':'OR','pennsylvania':'PA','rhode island':'RI','south carolina':'SC','south dakota':'SD',
 'tennessee':'TN','texas':'TX','utah':'UT','vermont':'VT','virginia':'VA','washington':'WA','west virginia':'WV',
 'wisconsin':'WI','wyoming':'WY','district of columbia':'DC'}
ABBRS = set(STATES.values())
FOREIGN = ['canada','india','united kingdom','uk','germany','france','ireland','australia','singapore','japan',
 'brazil','mexico','poland','spain','netherlands','israel','emea','apac','latam','london','toronto','bangalore',
 'berlin','dublin','sydney','tokyo']
SYNONYMS = [('front end','frontend'),('back end','backend'),('full stack','fullstack'),
            ('software development engineer','sde'),('software dev engineer','sde')]


def norm(s: str) -> str:
    s = re.sub(r'[^a-z0-9+#. ]+', ' ', (s or '').lower().replace('-', ' '))
    s = ' ' + re.sub(r'\s+', ' ', s).strip() + ' '
    for a, b in SYNONYMS:
        s = s.replace(f' {a} ', f' {b} ')
    return s


def contains_phrase(text: str, phrase: str) -> bool:
    p = norm(phrase).strip()
    return bool(p) and f' {p} ' in norm(text)


def parse_location(loc: str, title: str = ''):
    """Returns dict(city, state, country, workplace_type, foreign). country is 'US' or None (unclear/foreign)."""
    loc = loc or ''
    low = loc.lower()
    both = f'{low} {title.lower()}'
    workplace = 'unspecified'
    if 'hybrid' in both:
        workplace = 'hybrid'
    elif 'remote' in both:
        workplace = 'remote'

    state = None
    m = re.search(r',\s*([A-Z]{2})\b', loc)
    if m and m.group(1) in ABBRS:
        state = m.group(1)
    else:
        for name, ab in STATES.items():
            if re.search(rf'\b{name}\b', low):
                state = ab
                break
    us_word = bool(re.search(r'\b(united states|usa|u\.s\.?|us)\b', low)) or 'america' in low
    foreign = any(re.search(rf'\b{re.escape(f)}\b', low) for f in FOREIGN)
    country = 'US' if (state or us_word) and not (foreign and not state) else None
    city = loc.split(',')[0].strip() if state and ',' in loc else None
    return {'city': city, 'state': state, 'country': country, 'workplace_type': workplace,
            'foreign': foreign}


def infer_experience(title: str) -> str:
    t = norm(title)
    rules = [('internship', ['intern', 'internship', 'co op']), ('principal', ['principal', 'distinguished']),
             ('lead', ['lead', 'staff', 'manager']), ('senior', ['senior', 'sr']),
             ('entry', ['entry level', 'new grad', 'graduate', 'associate', 'junior', 'jr', 'sde i',
                        'engineer i', 'software engineer 1']),
             ('mid', ['sde ii', 'engineer ii', 'software engineer 2', 'mid level'])]
    for level, words in rules:
        if any(f' {w} ' in t for w in words):
            return level
    return 'unspecified'


def fingerprint(company: str, title: str, location: str) -> str:
    key = '|'.join([norm(company).strip(), norm(title).strip(), norm(location).strip()])
    return hashlib.sha1(key.encode()).hexdigest()


def is_older_than(posted_at, days: int) -> bool:
    """True only if we KNOW the posting date and it is older than `days`. Unknown date -> False."""
    if not posted_at:
        return False
    try:
        dt = datetime.fromisoformat(str(posted_at).replace('Z', '+00:00'))
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt < datetime.now(timezone.utc) - timedelta(days=days)


def match_profiles(job: dict, profiles: list[dict]) -> list[int]:
    """Return ids of every active profile this job satisfies."""
    ids = []
    for p in profiles:
        if not any(contains_phrase(job['title'], t) for t in p['titles']):
            continue
        if any(contains_phrase(job['title'], k) for k in p['exclude_keywords']):
            continue
        if p.get('max_age_days') and is_older_than(job.get('posted_at'), p['max_age_days']):
            continue
        if p['include_keywords']:
            blob = f"{job['title']} {job.get('description') or ''}"
            if not any(contains_phrase(blob, k) for k in p['include_keywords']):
                continue
        if job['country'] != 'US' and not (p['include_unclear_location'] and not job['foreign']):
            continue
        if p['states'] and job['state'] not in p['states'] and job['workplace_type'] != 'remote':
            continue
        if p['workplace_types'] and job['workplace_type'] not in p['workplace_types'] \
                and job['workplace_type'] != 'unspecified':
            continue
        if p.get('employment_types') and job.get('employment_type', 'unspecified') not in p['employment_types'] \
                and job.get('employment_type', 'unspecified') != 'unspecified':
            continue
        if p['experience_levels'] and job['experience_level'] not in p['experience_levels'] \
                and job['experience_level'] != 'unspecified':
            continue
        ids.append(p['id'])
    return ids
