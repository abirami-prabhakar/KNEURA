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


# Class-level labels support these statements, not tear grades, measurements,
# severity, normal structures or treatment recommendations.
TEMPLATE = {
    'ACL': ('Anterior cruciate ligament abnormality.', 'Anterior cruciate ligament abnormality'),
    'MCL': ('Medial collateral ligament abnormality.', 'Medial collateral ligament abnormality'),
    'Medial Meniscus': ('Abnormality involving the medial meniscus.', 'Medial meniscal abnormality'),
    'Lateral Meniscus': ('Abnormality involving the lateral meniscus.', 'Lateral meniscal abnormality'),
    'Medial OA': ('Osteoarthritic changes in the medial tibiofemoral compartment.', 'Medial tibiofemoral osteoarthritis'),
    'Lateral OA': ('Osteoarthritic changes in the lateral tibiofemoral compartment.', 'Lateral tibiofemoral osteoarthritis'),
    'Patellofemoral OA': ('Osteoarthritic changes in the patellofemoral compartment.', 'Patellofemoral osteoarthritis'),
    'Effusion': ('Knee joint effusion.', 'Knee joint effusion'),
    'Synovitis': ('Synovitis involving the knee joint.', 'Knee joint synovitis'),
    "Baker's cyst": ("Popliteal (Baker's) cyst.", "Popliteal (Baker's) cyst"),
    'Contusion': ('Bone contusion.', 'Bone contusion'),
    'Fracture': ('Fracture.', 'Fracture'),
}


def compose(approved):
    by_name = {f['name']: f for f in approved}
    if len(by_name) != len(approved) or not set(by_name).issubset(TEMPLATE):
        raise ValueError('Template requires unique canonical approved findings.')
    statements = []
    for section in ('findings', 'impression'):
        for name in NAMES:
            if name not in by_name:
                continue
            finding = by_name[name]
            text = TEMPLATE[name][0] if section == 'findings' else TEMPLATE[name][1] + '.'
            statements.append(dict(id=f"{section}-{finding['id']}", text=text,
                                   findingIds=[finding['id']], source='approved-finding', section=section))
    if not approved:
        for section in ('findings', 'impression'):
            statements.append(dict(id=section + '-limitation',
                text='No reportable abnormalities are established by the supplied findings. This does not establish a normal examination.',
                findingIds=[], source='template-limitation', section=section))
    findings = '\n'.join(s['text'] for s in statements if s['section'] == 'findings')
    impression = '\n'.join(s['text'] for s in statements if s['section'] == 'impression')
    return findings, impression, statements, 'Evidence-bound template'


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
