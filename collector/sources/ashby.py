"""Ashby public job board API: https://api.ashbyhq.com/posting-api/job-board/<board>"""
import time

import salary as sal
from .base import MAX_DESC, country_hint, get_json, norm_employment

API = 'https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true'
WORKPLACE = {'remote': 'remote', 'hybrid': 'hybrid', 'onsite': 'onsite', 'on-site': 'onsite'}


class AshbyCollector:
    def fetch(self, board_token: str, company_name: str) -> list[dict]:
        data = get_json(None, API.format(token=board_token))
        time.sleep(0.1)
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
                'salary': AshbyCollector._salary(j),
                'salary_checked': True,
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

    @staticmethod
    def _salary(j):
        comp = j.get('compensation') or {}
        comps = comp.get('summaryComponents') or []
        pick = next((c for c in comps if (c.get('compensationType') or '').lower() == 'salary'), None)
        if pick:
            out = sal.structured(pick.get('minValue'), pick.get('maxValue'), pick.get('currencyCode'), pick.get('interval'))
            if out:
                return out
        text = ' '.join(filter(None, [comp.get('scrapeableCompensationSalarySummary'),
                                      comp.get('compensationTierSummary'), j.get('descriptionPlain')]))
        return sal.extract(text)
