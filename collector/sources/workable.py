"""Workable public widget API: https://apply.workable.com/api/v1/widget/accounts/<account>?details=true
This is the least-documented of the four sources, so it is the most likely to need a tweak."""
import time

import salary as sal
from .base import clean_html, country_hint, get_json, norm_employment

API = 'https://apply.workable.com/api/v1/widget/accounts/{token}?details=true'


class WorkableCollector:
    def fetch(self, board_token: str, company_name: str) -> list[dict]:
        data = get_json(None, API.format(token=board_token))
        time.sleep(0.1)
        return self.parse(data, company_name)

    @staticmethod
    def parse(data, company_name: str) -> list[dict]:
        if not isinstance(data, dict) or 'jobs' not in data:
            raise ValueError(f'Unexpected Workable response: {str(data)[:120]}')
        jobs = []
        for j in data['jobs']:
            code = j.get('shortcode') or j.get('id')
            if not code:
                continue
            location = ', '.join(x for x in (j.get('city'), j.get('state'), j.get('country')) if x)
            desc = clean_html(j.get('description'))
            jobs.append({
                'salary': sal.extract(desc), 'salary_checked': True,
                'source_job_id': str(code),
                'title': (j.get('title') or '').strip(),
                'company': company_name,
                'location': location,
                'description': desc,
                'application_url': j.get('url') or j.get('application_url') or '',
                'posted_at': j.get('published_on'),  # created_at is deliberately NOT used as a posting date
                'last_updated_at': None,
                'workplace_hint': 'remote' if j.get('telecommuting') else None,
                'country_hint': country_hint(j.get('country')),
                'employment_type': norm_employment(j.get('employment_type')),
            })
        return jobs
