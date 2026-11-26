"""Ashby public job board API: https://api.ashbyhq.com/posting-api/job-board/<board>"""
import time

from .base import MAX_DESC, country_hint, get_json, make_session, norm_employment

API = 'https://api.ashbyhq.com/posting-api/job-board/{token}'
WORKPLACE = {'remote': 'remote', 'hybrid': 'hybrid', 'onsite': 'onsite', 'on-site': 'onsite'}


class AshbyCollector:
    def __init__(self):
        self.session = make_session()

    def fetch(self, board_token: str, company_name: str) -> list[dict]:
        data = get_json(self.session, API.format(token=board_token))
        time.sleep(0.5)
        return self.parse(data, company_name)

    @staticmethod
    def parse(data, company_name: str) -> list[dict]:
        if not isinstance(data, dict) or 'jobs' not in data:
            raise ValueError(f'Unexpected Ashby response: {str(data)[:120]}')
        jobs = []
        for j in data['jobs']:
            if j.get('isListed') is False:
                continue
            addr = ((j.get('address') or {}).get('postalAddress')) or {}
            hint = WORKPLACE.get((j.get('workplaceType') or '').lower())
            if not hint and j.get('isRemote'):
                hint = 'remote'
            jobs.append({
                'source_job_id': str(j['id']),
                'title': (j.get('title') or '').strip(),
                'company': company_name,
                'location': j.get('location') or '',
                'description': (j.get('descriptionPlain') or '')[:MAX_DESC],
                'application_url': j.get('jobUrl') or j.get('applyUrl') or '',
                'posted_at': j.get('publishedAt'),
                'last_updated_at': None,
                'workplace_hint': hint,
                'country_hint': country_hint(addr.get('addressCountry')),
                'employment_type': norm_employment(j.get('employmentType')),
            })
        return jobs
