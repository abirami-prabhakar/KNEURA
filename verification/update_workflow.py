from pathlib import Path
import sqlite3
p=Path('backend 1/app/main.py'); s=p.read_text()
# Generic diagnostic endpoints are radiologist-only; downstream roles use their own projections.
s=s.replace('current_user: User = Depends(get_current_user),','current_user: ReviewPrincipal = Depends(require_radiologist),')
# Draft edits cannot spoof approval; editing invalidates any previous explanation.
s=s.replace('    new_version_num = (report.current_version or 1) + 1', '''    try:
        content = json.loads(request.draft_content)
    except (ValueError, TypeError):
        content = None
    if isinstance(content, dict):
        content["status"] = "DRAFT"
        content["final_approval"] = "PENDING"
        request.draft_content = json.dumps(content, indent=2)
    report.patient_explanation = None
    new_version_num = (report.current_version or 1) + 1''')
needle='    try:\n        report.status = "APPROVED"'
s=s.replace(needle,'''    review = db.query(RadiologistReview).filter_by(study_id=study.study_id).order_by(RadiologistReview.id.desc()).first()
    decisions = db.query(ValidatedFinding).filter_by(review_id=review.id).all() if review else []
    reviewed = {v.finding for v in decisions if not v.is_radiologist_added and v.outcome in ("CONFIRMED", "EDITED", "REJECTED", "APPROVED")}
    if not set(CANONICAL_ABNORMALITIES).issubset(reviewed):
        raise HTTPException(status_code=409, detail="Complete all 12 finding decisions before approval.")

    try:
        report.status = "APPROVED"
        try:
            signed = json.loads(report.draft_content)
        except (ValueError, TypeError):
            signed = None
        if isinstance(signed, dict):
            signed["status"] = "APPROVED"
            signed["final_approval"] = "APPROVED"
            report.draft_content = json.dumps(signed, indent=2)''')
s=s.replace('            current_v.status = "APPROVED"','            current_v.status = "APPROVED"\n            current_v.content = report.draft_content')
# Only signed report content feeds patient generation, never internal review notes.
start=s.index('def generate_patient_explanation_endpoint('); end=s.index('@app.get(',start); section=s[start:end]
section=section.replace('    review = (','''    if report.status != "APPROVED" or study.workflow_state != WorkflowState.RADIOLOGIST_APPROVED.value:
        raise HTTPException(status_code=409, detail="Generate an explanation from a signed report before orthopedic review.")
    try:
        signed = json.loads(report.draft_content)
        authorized_text = "\\n".join(signed["findings"]) + "\\n" + signed["impression"]
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=409, detail="Patient explanation requires structured signed findings and impression.")

    review = (''')
section=section.replace('            validated_findings=validated_findings,','''            validated_findings=[{"finding": name, "outcome": "CONFIRMED", "details": None}
                                for name in canonical_abnormalities_in_text(authorized_text)],''')
section=section.replace('            clinical_context=review.notes,','            clinical_context=authorized_text,')
s=s[:start]+section+s[end:]
s=s.replace('.filter(Study.workflow_state == WorkflowState.RADIOLOGIST_APPROVED.value)', '.filter(Study.workflow_state.in_([WorkflowState.RADIOLOGIST_APPROVED.value, WorkflowState.ORTHOPEDIC_REVIEW.value, WorkflowState.PATIENT_RELEASED.value]))')
# Dedicated orthopedic projection, no raw predictions or internal radiologist notes.
start=s.index('def get_orthopedic_study('); end=s.index('@app.post(',start); section=s[start:end]
section=section.replace('    return OrthopedicStudyResponse(','''    ortho = db.query(OrthopedicReview).filter_by(study_id=study_id).order_by(OrthopedicReview.id.desc()).first()
    return OrthopedicStudyResponse(''')
section=section.replace('        clinical_context=None,','''        clinical_context=None,
        patient_id=study.patient_id,
        data_mode=study.data_mode,
        patient_explanation=report.patient_explanation,
        orthopedic_review={"assessment": ortho.assessment, "recommendation": ortho.recommendation,
                           "notes": ortho.notes, "patient_information_approved": ortho.patient_information_approved,
                           "approved_followup_info": ortho.approved_followup_info} if ortho else None,''')
s=s[:start]+section+s[end:]
s=s.replace('True if request.patient_information_approved is None else request.patient_information_approved','request.patient_information_approved is True')
needle='    patient_info_approved = ('
s=s.replace(needle,'''    if request.patient_information_approved and not report.patient_explanation:
        raise HTTPException(status_code=409, detail="Radiologist must generate the patient explanation before patient-information approval.")

'''+needle)
needle='    # 2. Study must have undergone orthopedic review'
s=s.replace(needle,'''    if not report.patient_explanation:
        raise HTTPException(status_code=409, detail="Patient explanation is required before release.")

'''+needle)
p.write_text(s)
p=Path('backend 1/app/schemas.py'); s=p.read_text().replace('    clinical_context: str | None = None','''    clinical_context: str | None = None
    patient_id: str | None = None
    data_mode: str | None = None
    patient_explanation: str | dict | None = None
    orthopedic_review: dict | None = None'''); s=s.replace('patient_information_approved: bool = True','patient_information_approved: bool = False'); p.write_text(s)
p=Path('backend 1/app/models/orthopedic_review.py'); s=p.read_text().replace('default=True','default=False'); p.write_text(s)
p=Path('backend 1/scripts/serve_mock_provider.py'); s=p.read_text(); s=s.replace('    return SimpleNamespace(text=json.dumps(result))','''    if 'patient-friendly explanation assistant' in prompt:
        names = [item['abnormality'] for item in approved]
        terms = {"MCL": "MCL is the ligament along the inner side of the knee.",
                 "Effusion": "Effusion means fluid in the knee joint."}
        result = {
            'title': 'Patient-Friendly MRI Explanation', 'study_id': study_id,
            'approved_findings': ', '.join(names),
            'what_this_means': ' '.join(terms.get(name, name + ' is listed in your approved report.') for name in names),
            'important_note': 'MOCK PROVIDER — demonstration only. This explanation is based on radiologist-approved information. Please discuss your MRI results with your doctor for clinical interpretation and next steps.',
        }
    return SimpleNamespace(text=json.dumps(result))'''); p.write_text(s)
# Preserve the starting demo state before the authorized clinical journey.
with sqlite3.connect('kneura_demo.db') as db:
    print(db.execute('select email, role from users').fetchall())
    with sqlite3.connect('verification/before_clinical_journey.db') as backup: db.backup(backup)
