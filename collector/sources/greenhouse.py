"""Greenhouse public Job Board API (official, no key).
Docs: https://developers.greenhouse.io/job-board.html
Two-step by design: the cheap job LIST (no descriptions) for every board, then a per-job DETAIL call only for
jobs that already passed your filters and have not been salary-checked yet."""
import time

import salary as sal
from .base import clean_html, get_json, get_session

LIST_URL = 'https://boards-api.greenhouse.io/v1/boards/{token}/jobs'
DETAIL_URL = 'https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{id}?pay_transparency=true'


class GreenhouseCollector:
    def fetch(self, board_token: str, company_name: str) -> list[dict]:
        data = get_json(None, LIST_URL.format(token=board_token))
        time.sleep(0.1)
        return self.parse(data, company_name)

    @staticmethod
    def parse(data, company_name: str) -> list[dict]:
        if not isinstance(data, dict) or 'jobs' not in data:
            raise ValueError(f'Unexpected Greenhouse response: {str(data)[:120]}')
        jobs = []
        for j in data['jobs']:
            jobs.append({
                'source_job_id': str(j['id']),
                'title': (j.get('title') or '').strip(),
                'company': company_name,
                'location': (j.get('location') or {}).get('name', ''),
                'description': '',
                'application_url': j.get('absolute_url', ''),
                # first_published is the real posting time when present; updated_at is NOT a posting date.
                'posted_at': j.get('first_published'),
                'last_updated_at': j.get('updated_at'),
                'salary': None,
                'salary_checked': False,   # becomes True once the detail call has been made
            })
        return jobs

    def detail(self, board_token: str, job_id: str) -> dict:
        j = get_json(None, DETAIL_URL.format(token=board_token, id=job_id))
        time.sleep(0.1)
        return self.parse_detail(j)

    @staticmethod
    def parse_detail(j: dict) -> dict:
        salary = None
        for r in j.get('pay_input_ranges') or []:
            lo = (r.get('min_cents') or 0) / 100 or None
            hi = (r.get('max_cents') or 0) / 100 or None
            salary = sal.structured(lo, hi, r.get('currency_type'), None)
            if salary:
                break
        return {'posted_at': j.get('first_published'), 'text': clean_html(j.get('content')), 'salary': salary}
