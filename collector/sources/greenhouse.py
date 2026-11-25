"""Greenhouse public Job Board API (official, no key needed, intended for this use).
Docs: https://developers.greenhouse.io/job-board.html
"""
import html
import re
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API = 'https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true'
MAX_DESC = 15000  # keep the free 500MB database small


def _session():
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])
    s.mount('https://', HTTPAdapter(max_retries=retry))
    s.headers['User-Agent'] = 'FreshJobsTracker/0.1 (personal job board; polite polling)'
    return s


def _clean(content: str) -> str:
    text = html.unescape(content or '')           # Greenhouse returns HTML-escaped HTML
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html.unescape(re.sub(r'\s+', ' ', text)).strip()
    return text[:MAX_DESC]


class GreenhouseCollector:
    def __init__(self):
        self.session = _session()

    def fetch(self, board_token: str, company_name: str) -> list[dict]:
        """Raises on failure (404 = bad token). Caller records the error per board."""
        r = self.session.get(API.format(token=board_token), timeout=30)
        r.raise_for_status()
        jobs = []
        for j in r.json().get('jobs', []):
            jobs.append({
                'source_job_id': str(j['id']),
                'title': j.get('title', '').strip(),
                'company': company_name,
                'location': (j.get('location') or {}).get('name', ''),
                'description': _clean(j.get('content')),
                'application_url': j.get('absolute_url', ''),
                # first_published is the real original posting time when present.
                # updated_at is NOT a posting date, so it is never used as one.
                'posted_at': j.get('first_published'),
                'last_updated_at': j.get('updated_at'),
            })
        time.sleep(0.5)  # be polite between boards
        return jobs
