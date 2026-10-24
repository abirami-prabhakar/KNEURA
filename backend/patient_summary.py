"""Reviewed plain-language companion to the immutable clinical report.

The starter explains approved class labels, not free-text clinical conclusions.
An orthopedist must reconcile it with the final report before publication.
"""
from copy import deepcopy
import hashlib
import json

from fastapi import Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field


LIMITATION = ('This summary explains the reviewed MRI findings. It does not by itself '
              'show how severe a problem is or decide which treatment you need. '
              'Your clinician considers the scan together with your symptoms and examination.')
EXPLANATIONS = {
    'ACL': 'A change was noted in the ACL, a band of tissue that helps keep the knee stable.',
    'MCL': 'A change was noted in the MCL, a band of tissue on the inner side of the knee.',
    'Medial Meniscus': 'A change was noted in the cushioning tissue on the inner side of the knee.',
    'Lateral Meniscus': 'A change was noted in the cushioning tissue on the outer side of the knee.',
    'Medial OA': 'Arthritis-related changes were noted on the inner side of the knee joint.',
    'Lateral OA': 'Arthritis-related changes were noted on the outer side of the knee joint.',
    'Patellofemoral OA': 'Arthritis-related changes were noted where the kneecap meets the thigh bone.',
    'Effusion': 'Extra fluid was noted inside the knee joint.',
    'Synovitis': 'Inflammation was noted in the lining of the knee joint.',
    "Baker's cyst": 'A pocket of fluid was noted behind the knee.',
    'Contusion': 'A bone bruise was noted.',
    'Fracture': 'A break or crack in a bone was noted.',
}
EXPLANATIONS['PF OA'] = EXPLANATIONS['Patellofemoral OA']
EXPLANATIONS["Baker's"] = EXPLANATIONS["Baker's cyst"]


def source_fingerprint(case):
    source = {'report': case.get('report'), 'findings': [
        {'id': f['id'], 'name': f['name'], 'status': f['status']}
        for f in case['findings']]}
    return hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()


def reviewed_current(case):
    summary = case.get('patientSummary') or {}
    return (summary.get('status') in ('REVIEWED', 'RELEASED')
            and bool(summary.get('reviewedById')) and bool(summary.get('reviewedAt'))
            and summary.get('sourceFingerprint') == source_fingerprint(case))


def draft(case):
    approved = [f for f in case['findings'] if f['status'] == 'APPROVED']
    lines = [EXPLANATIONS.get(f['name'], f"A finding labelled {f['name']} was approved. Ask your clinician to explain it.")
             for f in approved]
    return dict(status='DRAFT', version=0, sourceFingerprint=source_fingerprint(case),
                sourceReportId=case['report'].get('id'), sourceReportVersion=case['report'].get('version'),
                approvedFindingIds=[f['id'] for f in approved],
                findings='\n'.join(lines) if lines else
                    'No findings were approved from the computer-assisted review. This does not mean the whole scan is normal. Your clinician must explain the final report.',
                meaning='', nextSteps='', limitation=LIMITATION, revisions=[])


class SummaryReview(BaseModel):
    findings: str = Field(min_length=1, max_length=12000)
    meaning: str = Field(min_length=1, max_length=6000)
    nextSteps: str = Field(default='', max_length=6000)
    sourceFingerprint: str = Field(min_length=64, max_length=64)
    version: int = Field(ge=0)
    confirmed: bool = False


def install(api):
    def orthopedist(account=Depends(api.user)):
        if account['role'] != 'orthopedist':
            raise HTTPException(403, 'An orthopedist must review the patient summary.')
        return account

    def final_case(case_id):
        case = api.get_case(case_id)
        if case['status'] != 'FINAL' or case.get('report', {}).get('status') != 'FINAL':
            raise HTTPException(409, 'Finalize the clinical report before preparing the patient summary.')
        return case

    @api.app.post('/api/cases/{case_id}/patient-summary')
    def prepare(case_id: str, account=Depends(orthopedist)):
        with api.LOCK:
            case = final_case(case_id)
            previous = case.get('patientSummary')
            if previous and previous.get('sourceFingerprint') == source_fingerprint(case):
                return api.visible(case, account)
            summary = draft(case)
            if previous:
                summary['revisions'] = previous.get('revisions', []) + [
                    {k: v for k, v in previous.items() if k != 'revisions'}]
                summary['version'] = previous.get('version', 0) + 1
            case['patientSummary'] = summary
            api.event(case, 'Patient summary draft prepared from approved findings', account['name'],
                      actor_id=account['id'], current='DRAFT')
            api.save_case(case)
            return api.visible(case, account)

    @api.app.patch('/api/cases/{case_id}/patient-summary')
    def review(case_id: str, body: SummaryReview, account=Depends(orthopedist)):
        if not body.confirmed or not body.findings.strip() or not body.meaning.strip():
            raise HTTPException(422, 'Explain the findings and meaning, then confirm review against the final clinical report.')
        with api.LOCK:
            case = final_case(case_id)
            summary = case.get('patientSummary')
            if (not summary or body.sourceFingerprint != source_fingerprint(case)
                    or summary.get('sourceFingerprint') != body.sourceFingerprint
                    or summary.get('version') != body.version):
                raise HTTPException(409, 'The report or summary changed. Reload and review the current version.')
            previous = {k: deepcopy(v) for k, v in summary.items() if k != 'revisions'}
            summary['revisions'].append(previous)
            summary.update(findings=body.findings.strip(), meaning=body.meaning.strip(), nextSteps=body.nextSteps.strip(),
                           limitation=LIMITATION, version=summary['version'] + 1,
                           reviewedBy=account['name'], reviewedById=account['id'], reviewedAt=api.now(),
                           status='RELEASED' if case.get('releasedToPatient') else 'REVIEWED')
            api.event(case, 'Patient summary reviewed' + (' and published' if case.get('releasedToPatient') else ''),
                      account['name'], actor_id=account['id'], previous=previous['status'], current=summary['status'])
            api.save_case(case)
            return api.visible(case, account)

    @api.app.get('/api/cases/{case_id}/patient-summary/export')
    def export(case_id: str, account=Depends(api.user)):
        with api.LOCK:
            case = final_case(case_id)
            api.visible(case, account)
            if not case.get('releasedToPatient') or not reviewed_current(case):
                raise HTTPException(409, 'A reviewed and released patient summary is required before sharing.')
            summary = case['patientSummary']
            patient = case.get('patient') or {}
            name = patient.get('name') or case['study'].get('patientName', 'Not supplied')
            text = '\n\n'.join([
                'KNEURA — Your knee MRI summary',
                f"Patient: {name}\nCase: {case['id']}\nStudy: {case['study'].get('description', '')}",
                'What was found\n' + summary['findings'], 'What this means\n' + summary['meaning'],
                'Next steps from your orthopedist\n' + (summary['nextSteps'] or 'No next steps have been added. Ask your care team for your plan.'),
                'What this summary can tell you\n' + summary['limitation'],
                f"Reviewed by: {summary['reviewedBy']}\nReviewed at: {summary['reviewedAt']}\nSummary version: {summary['version']}",
                'The original clinical report is available separately from your care team.',
            ])
            api.event(case, 'Released patient summary exported', account['name'], actor_id=account['id'],
                      current={'summaryVersion': summary['version']})
            api.save_case(case)
        return Response(text, media_type='text/plain; charset=utf-8', headers={
            'Content-Disposition': 'attachment; filename="kneura-patient-summary.txt"', 'Cache-Control': 'no-store'})
