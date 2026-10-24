# Offline report template

In a case's Report tab, review all 12 findings, expand **Use a template instead (not LLM generated)** and select **Generate template draft**. No LLM credentials, network connection or new dependency is needed for this path.

For approved ACL, Medial Meniscus and Effusion findings, the generated draft is:

## Findings

Anterior cruciate ligament abnormality.
Abnormality involving the medial meniscus.
Knee joint effusion.

## Impression

Anterior cruciate ligament abnormality.
Medial meniscal abnormality.
Knee joint effusion.

Patient and study details are displayed by the existing report header. Draft/provider labels remain separate from clinical prose. Each statement links to its supporting approved finding. Rejected findings are omitted, not interpreted as normal structures. The template never infers tear type, severity, measurements, location beyond the approved label, technique or treatment. Cases with no approved findings explicitly state that a normal examination is not established.

The radiologist reviews the MRI, edits the draft as appropriate and selects **Save reviewed report**, then **Approve final**. Orthopedist review and patient release are unchanged. The LLM workflow remains available; failed LLM requests are not silently presented as template successes. Choose the template explicitly once the report job has failed or finished.

Existing saved reports are not rewritten. Deploy frontend and backend together. No database migration is required.
