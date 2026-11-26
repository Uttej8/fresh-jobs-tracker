"""Salary extraction. Two sources only: structured fields from the vendor, or an explicit range in the posting
text. Nothing is ever estimated. Returns None when no salary is stated."""
import re

SYM = {'USD': '$', 'GBP': '£', 'EUR': '€', 'CAD': 'C$', 'AUD': 'A$'}
CUR = {'$': 'USD', '£': 'GBP', '€': 'EUR'}
NUM = r'(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s?([kK])?'
RANGE = re.compile(r'([$£€])\s?' + NUM + r'\s*(?:-|–|—|to)\s*(?:[$£€]\s?)?' + NUM)
BAD = ('raised', 'funding', 'valuation', 'revenue', 'series ', 'million', 'billion', ' arr ')


def norm_period(s):
    s = (s or '').lower()
    for key, name in (('hour', 'hour'), ('year', 'year'), ('annual', 'year'), ('month', 'month'),
                      ('week', 'week'), ('day', 'day')):
        if key in s:
            return name
    return None


def _infer_period(v):
    if v >= 15000:
        return 'year'
    return 'hour' if 8 <= v <= 500 else None


def _valid(lo, hi, period):
    if lo <= 0 or hi < lo or hi > lo * 4:
        return False
    return {'year': (15000, 2_000_000), 'hour': (8, 500), 'month': (1500, 100_000)}.get(period, (0, 0))[0] <= lo \
        and hi <= {'year': 2_000_000, 'hour': 500, 'month': 100_000}.get(period, 0)


def _fmt(v, period):
    return f'{v:,.0f}' if period != 'hour' else f'{v:,.2f}'.rstrip('0').rstrip('.')


def build(lo, hi, currency, period, source):
    s = SYM.get(currency, '')
    cur = f'{currency} ' if not s else ''
    text = (f'{cur}{s}{_fmt(lo, period)} - {s}{_fmt(hi, period)} / {period}' if hi != lo
            else f'{cur}{s}{_fmt(lo, period)} / {period}')
    return {'salary_min': lo, 'salary_max': hi, 'salary_currency': currency, 'salary_period': period,
            'salary_text': text, 'salary_source': source}


def structured(lo, hi, currency, period):
    """From vendor fields. Returns None unless there is at least one positive number."""
    try:
        lo = float(lo) if lo not in (None, '') else None
        hi = float(hi) if hi not in (None, '') else None
    except (TypeError, ValueError):
        return None
    lo, hi = lo or hi, hi or lo
    if not lo or lo <= 0 or hi < lo:
        return None
    period = norm_period(period) or _infer_period(lo)
    if not period:
        return None
    return build(lo, hi, (currency or 'USD').upper(), period, 'structured')


def extract(text):
    """Explicit ranges like '$120,000 - $150,000 per year' or '$55 - $70/hour' in posting text."""
    if not text:
        return None
    found = []
    for m in RANGE.finditer(text):
        sym, n1, k1, n2, k2 = m.groups()
        a, b = float(n1.replace(',', '')), float(n2.replace(',', ''))
        lo = a * (1000 if (k1 or (k2 and a < 1000)) else 1)
        hi = b * (1000 if k2 else 1)
        window = text[max(0, m.start() - 80): m.end() + 60].lower()
        if any(w in window for w in BAD):
            continue
        if 'equity' in window and not any(w in window for w in ('salary', 'base', 'compensation', 'annual', 'per year')):
            continue
        after = text[m.end(): m.end() + 40].lower()
        if re.search(r'\b(hour|hr|hourly)\b', after):
            period = 'hour'
        elif re.search(r'\b(month|mo)\b', after):
            period = 'month'
        elif re.search(r'\b(year|yr|annual|annually|annum)\b', after):
            period = 'year'
        else:
            period = _infer_period(lo)
        if not period or not _valid(lo, hi, period):
            continue
        cur = CUR[sym]
        if sym == '$':
            if re.search(r'\bcad\b|ca\$|c\$', window):
                cur = 'CAD'
            elif re.search(r'\baud\b|a\$|au\$', window):
                cur = 'AUD'
        key = (lo, hi, period, cur)
        if key not in [f[0] for f in found]:
            found.append((key, build(lo, hi, cur, period, 'description')))
    if not found:
        return None
    first = found[0][1]
    same = [f[1] for f in found if f[0][2] == first['salary_period'] and f[0][3] == first['salary_currency']][:4]
    out = dict(first)
    out['salary_min'] = min(s['salary_min'] for s in same)
    out['salary_max'] = max(s['salary_max'] for s in same)
    out['salary_text'] = ' | '.join(s['salary_text'] for s in same)
    return out
