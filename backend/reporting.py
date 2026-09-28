"""Explicit template fallback and report provenance. Narrative LLM is in narrative.py."""

from .inference import NAMES


def approved_findings(case):
    findings = case['findings']
    if (len(findings) != 12 or {f['name'] for f in findings} != set(NAMES)
            or len({f['id'] for f in findings}) != 12
            or any(f['status'] not in ('APPROVED', 'REJECTED') for f in findings)):
        raise ValueError('All 12 canonical findings require an explicit radiologist decision.')
    for finding in findings:
        decision = finding.get('decision') or {}
        if decision.get('status') != finding['status'] or not decision.get('userId') or not decision.get('timestamp'):
            raise ValueError('Every finding requires a persisted radiologist identity, timestamp and matching decision.')
    return [f for f in findings if f['status'] == 'APPROVED']


def compose(approved):
    statements = [dict(id='statement-' + f['id'], text=f"{f['name']}: abnormality approved by the reviewing radiologist.", findingIds=[f['id']], source='approved-finding') for f in approved]
    provider = 'Evidence-bound template'
    text = '\n'.join(s['text'] for s in statements) or 'No AI-proposed abnormalities were approved. This does not establish a normal examination.'
    return text, statements, provider


def edited_statements(findings, impression, approved, previous):
    # Preserve exact generated claims. Radiologist-authored text is explicitly
    # identified rather than falsely linking new clinical claims to model evidence.
    prior = {s['text']: s for s in previous if s.get('source') in ('approved-finding', 'radiologist-linked')}
    result = []
    for section, text in [('findings', findings), ('impression', impression)]:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            old = prior.get(line)
            result.append(dict(id=f'{section}-{len(result)}', text=line,
                               findingIds=old['findingIds'] if old else [],
                               source=old['source'] if old else 'radiologist-authored',
                               **({key: old[key] for key in ('evidenceIds', 'attachedById', 'attachedBy', 'attachedAt') if key in old} if old else {})))
    return result
