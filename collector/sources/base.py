"""Shared helpers for the source collectors."""
import html
import re
import threading

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

MAX_DESC = 15000  # keep the free 500MB database small


def make_session():
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])
    s.mount('https://', HTTPAdapter(max_retries=retry))
    s.headers['User-Agent'] = 'FreshJobsTracker/0.2 (personal job board; polite polling)'
    return s


_local = threading.local()


def get_session():
    """One requests session per thread (sessions are not guaranteed thread-safe)."""
    if not hasattr(_local, 's'):
        _local.s = make_session()
    return _local.s


def get_json(session, url):
    r = (session or get_session()).get(url, timeout=(10, 25))
    r.raise_for_status()
    return r.json()


def clean_html(raw: str) -> str:
    text = html.unescape(raw or '')
    text = re.sub(r'<[^>]+>', ' ', text)
    return html.unescape(re.sub(r'\s+', ' ', text)).strip()[:MAX_DESC]


def norm_employment(s: str) -> str:
    t = (s or '').lower().replace('-', ' ').replace('_', ' ')
    if 'intern' in t:
        return 'internship'
    if 'part' in t:
        return 'part_time'
    if any(w in t for w in ('contract', 'temp', 'freelance')):
        return 'contract'
    if 'full' in t:
        return 'full_time'
    return 'unspecified'


US_NAMES = {'us', 'usa', 'u.s.', 'united states', 'united states of america'}


def country_hint(value) -> str:
    """'US' for United States, upper-cased original for anything else, '' if unknown."""
    v = (value or '').strip()
    if not v:
        return ''
    return 'US' if v.lower() in US_NAMES else v.upper()
