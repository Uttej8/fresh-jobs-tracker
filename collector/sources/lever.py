"""Lever public postings API: https://api.lever.co/v0/postings/<company>?mode=json
(EU-hosted accounts use api.eu.lever.co; not supported yet.)"""
import time
from datetime import datetime, timezone

import salary as sal
from .base import MAX_DESC, country_hint, get_json, norm_employment

API = 'https://api.lever.co/v0/postings/{token}?mode=json'
WORKPLACE = {'remote': 'remote', 'hybrid': 'hybrid', 'on-site': 'onsite', 'onsite': 'onsite'}


class LeverCollector:
    def fetch(self, board_token: str, company_name: str) -> list[dict]:
        data = get_json(None, API.format(token=board_token))
        time.sleep(0.1)
        return self.parse(data, company_name)

    @staticmethod
    def parse(data, company_name: str) -> list[dict]:
        if not isinstance(data, list):
            raise ValueError(f'Unexpected Lever response: {str(data)[:120]}')
        jobs = []
        for j in data:
            cat = j.get('categories') or {}
            created = j.get('createdAt')  # milliseconds since epoch = real posting creation time
            posted = (datetime.fromtimestamp(created / 1000, tz=timezone.utc).isoformat()
                      if isinstance(created, (int, float)) else None)
            sr = j.get('salaryRange') or {}
            text = ' '.join(filter(None, [j.get('descriptionPlain'), j.get('additionalPlain'),
                                           j.get('salaryDescriptionPlain')]))
            salary = (sal.structured(sr.get('min'), sr.get('max'), sr.get('currency'), sr.get('interval'))
                      or sal.extract(text))
            jobs.append({
                'source_job_id': str(j['id']),
                'title': (j.get('text') or '').strip(),
                'company': company_name,
                'location': cat.get('location') or '',
                'description': (j.get('descriptionPlain') or '')[:MAX_DESC],
                'salary': salary,
                'salary_checked': True,
                'application_url': j.get('hostedUrl') or j.get('applyUrl') or '',
                'posted_at': posted,
                'last_updated_at': None,
                'workplace_hint': WORKPLACE.get((j.get('workplaceType') or '').lower()),
                'country_hint': country_hint(j.get('country')),
                'employment_type': norm_employment(cat.get('commitment')),
            })
        return jobs
