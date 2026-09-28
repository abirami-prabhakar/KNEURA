"""Persisted report job orchestration using FastAPI's existing background worker.

Only short read/commit sections hold the workflow lock. Network work never does.
"""
import uuid
from . import narrative
from .audit import event, now, digest


ACTIVE = ('QUEUED', 'PROCESSING')


def fingerprint(case):
    return digest([dict(id=f['id'], status=f['status'], decision=f.get('decision')) for f in case['findings']])


def run(service, case_id, job_id, payload, account):
    with service.LOCK:
        case = service.get_case(case_id)
        job = case.get('reportJob', {})
        if job.get('id') != job_id or job.get('status') != 'QUEUED':
            return
        job.update(status='PROCESSING', updatedAt=now())
        event(case, 'Narrative report job processing', account['name'], actor_id=account['id'], object_id=job_id)
        service.save_case(case)
    try:
        result, provider = narrative.generate(payload)
        with service.LOCK:
            case = service.get_case(case_id)
            job = case['reportJob']
            if job['id'] != job_id or job['status'] != 'PROCESSING' or case.get('report') or fingerprint(case) != job['decisionFingerprint']:
                raise ValueError('Case changed during generation; draft was not published.')
            case['report'] = dict(id=uuid.uuid4().hex, status='DRAFT', findings=result.findings, impression=result.impression,
                updatedAt=now(), createdAt=now(), createdBy=account['name'], createdById=account['id'],
                provider=f"Live LLM narrative / {provider['provider']} / {provider['model']}",
                providerModel=provider['model'], version=1, revisions=[],
                approvedFindingIds=result.source_finding_ids,
                statements=[dict(id=f'{job_id}-{index}', text=s.text, findingIds=s.finding_ids, section=s.section,
                                 source='approved-finding' if s.finding_ids else 'llm-context') for index, s in enumerate(result.statements)])
            case['status'] = 'DRAFT'
            job.update(status='COMPLETED', updatedAt=now(), reportId=case['report']['id'])
            event(case, 'LLM narrative draft generated from approved findings only', account['name'], actor_id=account['id'], object_id=job_id, current='DRAFT')
            service.save_case(case)
    except Exception as exc:
        service.LOG.error('Narrative report job failed: %s (%s)', job_id, type(exc).__name__)
        with service.LOCK:
            case = service.get_case(case_id)
            job = case.get('reportJob', {})
            if job.get('id') != job_id:
                return
            job.update(status='FAILED', updatedAt=now(), error='Narrative generation failed. Check LLM availability and output validation, then retry. No draft was saved.')
            event(case, 'LLM narrative job failed; approved findings preserved', account['name'], actor_id=account['id'], object_id=job_id, current='FAILED')
            service.save_case(case)
