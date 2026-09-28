"""Validate links before atomically persisting a case document in SQLite.

Study, series, images, analyses, evidence, decisions and report revisions are
owned by one case aggregate; there are no independently orphanable child rows.
"""


def validate_case_links(case):
    if not case.get('id') or not case.get('study', {}).get('id') or not case['study'].get('patientId'):
        raise ValueError('A case requires study and patient references.')
    series = {s['id']: s for s in case['series']}
    if len(series) != len(case['series']):
        raise ValueError('Duplicate series references.')
    images = [image['id'] for s in case['series'] for image in s['images']]
    if len(images) != len(set(images)):
        raise ValueError('Duplicate image references.')
    findings = {f['id']: f for f in case['findings']}
    if len(findings) != len(case['findings']):
        raise ValueError('Duplicate finding references.')
    for finding in findings.values():
        evidence = finding.get('evidence')
        if not evidence:
            continue
        source = series.get(evidence['seriesId'])
        if source is None:
            raise ValueError('Evidence must reference a series in the same case.')
        instances = {i['instanceNumber'] for i in source['images']}
        if not set(evidence.get('instanceNumbers', [evidence['sliceStart'], evidence['sliceEnd']])).issubset(instances):
            raise ValueError('Evidence must reference images in its source series.')
        if evidence.get('analysisId') and evidence['analysisId'] != case.get('analysis', {}).get('id'):
            raise ValueError('Evidence must reference this case analysis.')
    report = case.get('report')
    if report:
        approved = {f['id'] for f in findings.values() if f['status'] == 'APPROVED'}
        if set(report.get('approvedFindingIds', [])) != approved:
            raise ValueError('Report input must match approved findings in this case.')
        for statement in report.get('statements', []):
            if not set(statement['findingIds']).issubset(approved):
                raise ValueError('Report statements may only reference approved findings.')
    if any(a.get('caseId', case['id']) != case['id'] for a in case['audit']):
        raise ValueError('Audit events must belong to their case.')
