"""Pure-logic job parsing + filtering. No network, no DB: easy to test."""
import hashlib
import re
import unicodedata
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
# Foreign countries/regions AND major foreign tech-hub cities (checked on accent-folded text)
FOREIGN = ['canada','india','united kingdom','uk','england','scotland','germany','france','ireland','australia',
 'new zealand','singapore','japan','china','hong kong','taiwan','south korea','korea','brazil','mexico','argentina',
 'colombia','chile','costa rica','poland','spain','portugal','netherlands','belgium','sweden','norway','denmark',
 'finland','switzerland','austria','italy','czech republic','romania','serbia','ukraine','hungary','greece',
 'turkey','israel','egypt','nigeria','kenya','south africa','uae','dubai','saudi arabia','philippines','indonesia',
 'malaysia','vietnam','thailand','pakistan','bangladesh','sri lanka','georgia country','emea','apac','latam','europe',
 'asia','bangalore','bengaluru','hyderabad','pune','mumbai','delhi','gurgaon','gurugram','noida','chennai','kolkata',
 'toronto','montreal','ottawa','calgary','waterloo','vancouver bc','london','dublin','berlin','munich','paris',
 'amsterdam','warsaw','krakow','madrid','barcelona','lisbon','stockholm','copenhagen','oslo','helsinki','zurich',
 'tel aviv','tokyo','sydney','melbourne','sao paulo','buenos aires','mexico city','bogota','lagos','nairobi',
 'cape town','manila','jakarta','kuala lumpur','seoul','taipei','shanghai','beijing','shenzhen','bucharest',
 'belgrade','kyiv','prague','budapest','vienna','milan','rome','istanbul','cairo','tbilisi','yerevan','riga','tallinn']

# Remaining countries (so an unlisted "Remote - <country>" cannot slip through when unclear locations are on)
# plus Canadian provinces and Indian states. Puerto Rico and US territories are deliberately NOT here.
FOREIGN += ['afghanistan','albania','algeria','andorra','angola','armenia','azerbaijan','bahrain','barbados','belarus',
 'belize','benin','bhutan','bolivia','bosnia','botswana','brunei','bulgaria','burkina faso','cambodia','cameroon',
 'croatia','cuba','cyprus','denmark','dominican republic','ecuador','el salvador','estonia','ethiopia','fiji','ghana',
 'guatemala','haiti','honduras','iceland','iran','iraq','jamaica','jordan','kazakhstan','kuwait','kyrgyzstan','laos',
 'latvia','lebanon','libya','liechtenstein','lithuania','luxembourg','macedonia','madagascar','malta','mauritius',
 'moldova','monaco','mongolia','montenegro','morocco','mozambique','myanmar','namibia','nepal','nicaragua','oman',
 'panama','paraguay','peru','qatar','rwanda','senegal','slovakia','slovenia','sudan','syria','tanzania','tunisia',
 'turkmenistan','uganda','uruguay','uzbekistan','venezuela','yemen','zambia','zimbabwe',
 'ontario','quebec','british columbia','alberta','manitoba','saskatchewan','nova scotia','new brunswick',
 'newfoundland','karnataka','maharashtra','tamil nadu','telangana','kerala','gujarat','haryana','uttar pradesh']

# State codes that are ALSO country codes (CA Canada, IN India, DE Germany...). A bare ", IN" proves nothing,
# so these only count as US when no foreign signal is present.
AMBIG_CODES = {'CA','IN','DE','IL','CO','MA','ID','GA','AL','PA','AR','AZ','LA','MD','ME','MN','MT','NE','SC','SD',
               'TN','VA'}
# Codes that are ordinary words, so they never count without a preceding comma
BARE_BLOCK = {'OR','IN','ME','OK','HI','AS','LA','ID'}

# Unambiguous US cities: positive evidence when a posting gives only a city. Value = state (None if two states).
US_CITIES = {
 'new york city':'NY','new york':'NY','nyc':'NY','brooklyn':'NY','manhattan':'NY','long island city':'NY',
 'san francisco':'CA','south san francisco':'CA','oakland':'CA','berkeley':'CA','san jose':'CA','palo alto':'CA',
 'mountain view':'CA','sunnyvale':'CA','santa clara':'CA','menlo park':'CA','redwood city':'CA','cupertino':'CA',
 'fremont':'CA','san mateo':'CA','foster city':'CA','emeryville':'CA','santa cruz':'CA','los angeles':'CA',
 'santa monica':'CA','culver city':'CA','el segundo':'CA','pasadena':'CA','irvine':'CA','san diego':'CA',
 'sacramento':'CA','bay area':'CA','silicon valley':'CA','seattle':'WA','bellevue':'WA','redmond':'WA',
 'kirkland':'WA','austin':'TX','dallas':'TX','houston':'TX','san antonio':'TX','plano':'TX','irving':'TX',
 'frisco':'TX','boston':'MA','somerville':'MA','waltham':'MA','chicago':'IL','denver':'CO','boulder':'CO',
 'atlanta':'GA','miami':'FL','orlando':'FL','tampa':'FL','phoenix':'AZ','scottsdale':'AZ','tempe':'AZ',
 'tucson':'AZ','las vegas':'NV','salt lake city':'UT','lehi':'UT','provo':'UT','minneapolis':'MN','detroit':'MI',
 'ann arbor':'MI','columbus':'OH','cleveland':'OH','cincinnati':'OH','pittsburgh':'PA','philadelphia':'PA',
 'baltimore':'MD','washington dc':'DC','reston':'VA','mclean':'VA','raleigh':'NC','durham':'NC','charlotte':'NC',
 'nashville':'TN','st louis':'MO','saint louis':'MO','indianapolis':'IN','milwaukee':'WI','madison':'WI',
 'omaha':'NE','boise':'ID','albuquerque':'NM','honolulu':'HI','anchorage':'AK','new orleans':'LA',
 'jersey city':'NJ','hoboken':'NJ','princeton':'NJ','stamford':'CT','white plains':'NY',
 'portland':None,'arlington':None,'kansas city':None}
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


def _fold(text: str) -> str:
    """Remove accents (Sao Paulo, Zurich...) so matching is reliable."""
    return ''.join(c for c in unicodedata.normalize('NFKD', text or '') if not unicodedata.combining(c))


def parse_location(loc: str, title: str = ''):
    """Returns dict(city, state, country, workplace_type, foreign, confidence).
    country is 'US' or None. confidence: explicit (US word / unambiguous state), state (ambiguous code with no
    foreign signal), city (known US city), unclear. `foreign` = a foreign country/city was seen."""
    loc = _fold(loc or '')
    low = loc.lower()
    both = f'{low} {title.lower()}'
    workplace = 'unspecified'
    if 'hybrid' in both:
        workplace = 'hybrid'
    elif 'remote' in both:
        workplace = 'remote'

    t = ' ' + re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9 ]+', ' ', low)) + ' '
    foreign = any(f' {f} ' in t.replace(' new mexico ', ' ') for f in FOREIGN)

    state, ambiguous = None, False
    m = re.search(r',\s*([A-Z]{2})\b', loc)
    if m and m.group(1) in ABBRS:
        state, ambiguous = m.group(1), m.group(1) in AMBIG_CODES
    if not state:
        m = re.search(r'\s([A-Z]{2})$', loc.strip())          # "Austin TX" with no comma
        if m and m.group(1) in ABBRS and m.group(1) not in BARE_BLOCK:
            state, ambiguous = m.group(1), m.group(1) in AMBIG_CODES
    if not state:
        for name in sorted(STATES, key=len, reverse=True):       # longest first: 'west virginia' before 'virginia'
            if f' {name} ' in t:
                state, ambiguous = STATES[name], name == 'georgia'
                break
    city_state = next((st for c, st in sorted(US_CITIES.items(), key=lambda x: -len(x[0])) if f' {c} ' in t), False)

    us_word = bool(re.search(r'(?<![a-z])(united states(?: of america)?|usa|u\.s\.?|us)(?![a-z])', low))
    if us_word or (state and not ambiguous):
        country, conf = 'US', 'explicit'
    elif state and not foreign:
        country, conf = 'US', 'state'
    elif city_state is not False and not foreign:
        country, conf = 'US', 'city'
        state = state or city_state
    else:
        country, conf = None, 'unclear'
    city = loc.split(',')[0].strip() if state and ',' in loc else None
    return {'city': city, 'state': state if country else None, 'country': country, 'workplace_type': workplace,
            'foreign': foreign and country != 'US', 'confidence': conf}


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


def match_profiles(job: dict, profiles: list[dict], ignore_location: bool = False) -> list[int]:
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
        if not ignore_location:
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
