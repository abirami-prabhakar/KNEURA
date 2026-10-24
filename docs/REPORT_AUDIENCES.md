# Clinical report and patient summary

The orthopedist sees the original finalized clinical impression, detailed findings,
approval provenance and links to radiologist-approved MRI evidence. The clinical
report remains unchanged and can still be exported through the existing endpoint.

In **Clinical report & patient summary**, the orthopedist selects **Prepare patient
summary**, reviews the plain-language findings, writes their meaning for the patient
and optionally adds next steps. The explicit review checkbox and **Save reviewed
patient summary** record the review. **Approve for Patient Coordinator** then
releases both documents through the existing release state and API.

The coordinator sees the patient-friendly summary first. **Download patient summary**
exports a text document; **Print / Save patient summary PDF** uses the browser print
dialog. The original clinical report remains in a separate tab. These actions do not
send email or claim the patient has received the document.

## Content and review

The starter is a deterministic glossary of approved finding labels, not an LLM
rewrite of the clinical report. Rejected findings and model probabilities are not
included. It does not infer tear grades, severity, treatment or a normal scan when
no findings were approved. The orthopedist must reconcile the starter with the
clinical impression, preserving uncertainty and any radiologist-authored details.
Meaning and next steps are clinician-authored. A general limitation accompanies
every summary and cannot be removed through the review API.

Plain-language terminology references (not patient-specific recommendations):

- [AAOS: Knee anatomy and meniscus](https://www.orthoinfo.org/treatment/knee-arthroscopy/)
- [AAOS: Collateral ligaments](https://www.orthoinfo.org/diseases--conditions/collateral-ligament-injuries/)
- [NHS: Osteoarthritis](https://www.nhs.uk/conditions/osteoarthritis/)
- [NHS: Baker's cyst](https://www.nhs.uk/conditions/Bakers-cyst/)

## Storage and compatibility

`patientSummary` is an additive object in the existing case document. It records
the source-report fingerprint, approved finding IDs, summary version, reviewer,
timestamp and revision history. No database migration or replacement role is used.
The `patient` role still means Patient Coordinator.

- `POST /api/cases/{id}/patient-summary`: prepare an orthopedist-only draft.
- `PATCH /api/cases/{id}/patient-summary`: explicitly review/save; rejects stale
  source fingerprints and summary versions.
- `GET /api/cases/{id}/patient-summary/export`: download a reviewed and released
  summary, recording an audit event.

New releases require a current reviewed summary. Existing released cases retain
access to the clinical report; no summary is silently generated or approved.
An orthopedist can prepare a summary for such a case and explicitly **Approve and
publish updated summary**. Drafts, outdated summaries and internal revision history
are excluded from the coordinator view. Published revisions remain archived.
