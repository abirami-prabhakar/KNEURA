from pathlib import Path
p=Path('frontend/code.html'); s=p.read_text()
s=s.replace("return { ...await api(`/studies/${studyId}`), ...approved };", "return { ...approved, report: { status: 'APPROVED', draft_content: approved.approved_report, patient_explanation: approved.patient_explanation } };")
s=s.replace('      return api(`/studies/${studyId}`);', '''      const detail = await api(`/studies/${studyId}`);
      if (detail.report) detail.versions = await api(`/reports/${detail.report.report_id}/versions`);
      return detail;''')
start=s.index('    async function editReport()'); end=s.index('    async function generatePatientExplanation()',start)
s=s[:start]+'''    function editReport() {
      STATE.editingReport = true;
      render();
    }

    async function saveReport(event) {
      event.preventDefault();
      const form = new FormData(event.target);
      const report = STATE.pendingDetail.report;
      const parsed = parseContent(report.draft_content);
      const content = parsed && typeof parsed === 'object' && !Array.isArray(parsed)
        ? JSON.stringify({...parsed, findings: String(form.get('findings')).split('\\n').filter(line => line.trim()), impression: String(form.get('impression')), status: 'DRAFT', final_approval: 'PENDING'})
        : String(form.get('content'));
      STATE.submitting = true;
      render();
      try {
        await api(`/reports/${report.report_id}`, {method:'PUT', body:JSON.stringify({draft_content:content})});
        STATE.editingReport = false;
        await refreshStudyDetail();
        setNotification('Edited version saved. Explicit radiologist approval is still required.', 'success');
      } catch (error) { setNotification(error.message, 'error'); }
      finally { STATE.submitting = false; render(); }
    }

''' +s[end:]
# Reset editor on navigation/session change.
s=s.replace('      STATE.selectedStudyId = null;\n      STATE.pendingDetail', '      STATE.selectedStudyId = null;\n      STATE.editingReport = false;\n      STATE.pendingDetail')
s=s.replace("${escapeHtml(aiStatus)} • Report: ${escapeHtml(reportStatus)}", "${isOrthopedicRole(role) ? 'Approved radiology report' : escapeHtml(aiStatus)} • ${escapeHtml(workflowState)}")
s=s.replace('class="font-bold text-primary">${escapeHtml(study.study_id)}', 'class="font-bold text-primary break-all min-w-0">${escapeHtml(study.study_id)}')
s=s.replace('AI-assisted findings — Radiologist review required</div>', "${escapeHtml((detail.validated_findings || []).find(f => f.finding === label)?.outcome?.replace('APPROVED', 'CONFIRMED') || 'PENDING')}</div>")
s=s.replace('<button class="btn-primary-archival rounded px-3 py-1.5 font-label-caps-sm text-label-caps-sm uppercase" data-ai-analyze>', '<button ${detail?.workflow_state && detail.workflow_state !== \'AI_COMPLETE\' ? \'disabled\' : \'\'} class="btn-primary-archival rounded px-3 py-1.5 font-label-caps-sm text-label-caps-sm uppercase" data-ai-analyze>')
# Optional clinician-added finding already supported by the backend.
s=s.replace('      STATE.submitting = true;\n      render();\n      try {\n        await api(`/studies/${STATE.selectedStudyId}/review`,', '''      const added = String(form.get('added-finding') || '').trim();
      if (added) validatedFindings.push({finding:added, outcome:'CONFIRMED', details:String(form.get('added-details') || '').trim() || null, is_radiologist_added:true});
      STATE.submitting = true;
      render();
      try {
        await api(`/studies/${STATE.selectedStudyId}/review`,''')
s=s.replace('<div class="space-y-3">${rows}</div>', '''<div class="space-y-3">${rows}</div>
          <label class="block">Add a finding (optional)<input name="added-finding" class="w-full border rounded p-2" /></label>
          <label class="block">Added finding details<input name="added-details" class="w-full border rounded p-2" /></label>''')
start=s.index('    function renderPatientCard('); end=s.index('    function render() {',start)
s=s[:start]+'''    function parseContent(content) {
      if (typeof content === 'object') return content;
      try { return JSON.parse(content); } catch { return null; }
    }

    function renderReport(content, status = 'DRAFT') {
      const report = parseContent(content);
      if (!report || typeof report !== 'object' || !Array.isArray(report.findings)) {
        return `<pre class="whitespace-pre-wrap break-words">${escapeHtml(content || 'No report content available.')}</pre>`;
      }
      const approved = status === 'APPROVED';
      return `<article class="space-y-4 rounded border border-[#34497F]/40 bg-white p-5" data-formatted-report>
        <h3 class="text-title-lg font-bold text-primary">${escapeHtml(report.title)}</h3>
        <section><h4 class="font-bold">Findings</h4><ul class="list-disc pl-5 space-y-1">${report.findings.map(f => `<li>${escapeHtml(f)}</li>`).join('')}</ul></section>
        <section><h4 class="font-bold">Impression</h4><p class="whitespace-pre-wrap">${escapeHtml(report.impression)}</p></section>
        <section class="bg-[#F2F3FF] rounded p-3"><h4 class="font-bold">Provider / Safety Note</h4><p>${escapeHtml(report.note)}</p></section>
        <div class="flex flex-wrap gap-4 text-sm"><span><b>Report status:</b> ${approved ? 'RADIOLOGIST APPROVED' : 'DRAFT'}</span><span><b>Final approval:</b> ${approved ? 'APPROVED' : 'PENDING APPROVAL'}</span></div>
      </article>`;
    }

    function renderExplanation(content) {
      const explanation = parseContent(content);
      if (!explanation || typeof explanation !== 'object') return `<p>${escapeHtml(content || 'Not generated yet.')}</p>`;
      return `<section class="space-y-3 rounded bg-white border p-4"><h3 class="font-bold text-primary">${escapeHtml(explanation.title || 'Patient explanation')}</h3>
        <p><b>Approved findings:</b> ${escapeHtml(explanation.approved_findings)}</p>
        <p>${escapeHtml(explanation.what_this_means)}</p>
        <p class="text-sm bg-[#F2F3FF] p-3">${escapeHtml(explanation.important_note)}</p></section>`;
    }

    function renderEditor(report) {
      const parsed = parseContent(report.draft_content);
      return `<form id="report-editor" class="space-y-3 rounded border bg-white p-4"><h3 class="font-bold">Edit draft report</h3>
        ${parsed && Array.isArray(parsed.findings) ? `<label class="block">Findings (one per line)<textarea name="findings" rows="5" required class="w-full border rounded p-2">${escapeHtml(parsed.findings.join('\\n'))}</textarea></label><label class="block">Impression<textarea name="impression" rows="3" required class="w-full border rounded p-2">${escapeHtml(parsed.impression)}</textarea></label>` : `<textarea name="content" rows="8" required class="w-full border rounded p-2">${escapeHtml(report.draft_content)}</textarea>`}
        <button class="btn-primary-archival rounded px-4 py-2" type="submit">Save Edited Version</button>
        <button class="btn-secondary-archival rounded px-4 py-2" type="button" data-cancel-edit>Cancel</button></form>`;
    }

    async function loadMri(index = 0) {
      const studyId = STATE.selectedStudyId;
      const area = shell.querySelector('#mri-image');
      if (!area) return;
      area.innerHTML = '<p role="status">Loading actual MRI slice…</p>';
      try {
        const result = await api(`/studies/${studyId}/mri-preview?slice_index=${index}`);
        if (STATE.selectedStudyId !== studyId) return;
        STATE.mri = {studyId, ...result};
        drawMri();
      } catch (error) { if (STATE.selectedStudyId === studyId) area.textContent = error.message; }
    }

    function drawMri() {
      const area = shell.querySelector('#mri-image');
      const mri = STATE.mri;
      if (!area || mri?.studyId !== STATE.selectedStudyId) return;
      area.innerHTML = `<img src="${mri.image}" alt="Actual knee MRI DICOM slice ${mri.slice_index + 1}" class="mx-auto max-h-80 object-contain bg-black" /><div class="flex justify-center gap-4 items-center mt-2"><button data-prev-slice ${mri.slice_index === 0 ? 'disabled' : ''}>Previous slice</button><span>Slice ${mri.slice_index + 1} / ${mri.slice_count}</span><button data-next-slice ${mri.slice_index + 1 === mri.slice_count ? 'disabled' : ''}>Next slice</button></div>`;
      area.querySelector('[data-prev-slice]').onclick = () => loadMri(mri.slice_index - 1);
      area.querySelector('[data-next-slice]').onclick = () => loadMri(mri.slice_index + 1);
    }

    function renderDashboard() {
      const detail = STATE.pendingDetail;
      const role = STATE.session.role;
      const isPatient = role === 'PATIENT';
      const isRadiologist = role === 'RADIOLOGIST';
      const isOrthopedic = isOrthopedicRole(role);
      const state = detail?.workflow_state;
      const report = detail?.report;
      const reviewed = CANONICAL_ORDER.every(name => detail?.validated_findings?.some(f => f.finding === name && ['CONFIRMED','EDITED','REJECTED','APPROVED'].includes(f.outcome)));
      const canEdit = state === 'REPORT_DRAFT' && report?.status === 'DRAFT';
      const canRelease = isOrthopedic && state === 'ORTHOPEDIC_REVIEW' && detail.patient_id && detail.orthopedic_review?.patient_information_approved && detail.patient_explanation;
      const button = (attribute, label, enabled) => `<button ${attribute} ${enabled ? '' : 'disabled'} class="btn-secondary-archival rounded px-4 py-2 disabled:opacity-40 disabled:cursor-not-allowed">${label}</button>`;
      shell.innerHTML = `<div class="rounded-2xl border border-[#34497F] bg-[#F2F3FF] p-4 shadow-[4px_4px_0_0_#263B73]">
        <header class="flex flex-wrap justify-between gap-3 rounded border bg-[#FFF9EE] p-4 mb-4"><div><h2 class="text-title-lg font-bold text-primary">KNEURA Clinical Workspace</h2><p>${escapeHtml(STATE.session.email)} • ${isPatient ? 'PATIENT' : isOrthopedic ? 'ORTHOPEDICIAN' : 'RADIOLOGIST'}</p></div><button id="logout-button" class="btn-secondary-archival rounded px-4 py-2">Logout</button></header>
        ${STATE.loading || STATE.submitting ? '<p role="status" class="mb-3 bg-white p-3">Loading / saving — please wait…</p>' : ''}
        ${STATE.notification ? `<p role="alert" class="p-3 mb-3 rounded ${STATE.notification.variant === 'error' ? 'bg-red-100' : 'bg-green-100'}">${escapeHtml(STATE.notification.message)}</p>` : ''}
        <p class="mb-4 text-sm">DEMONSTRATION ONLY • ${isPatient ? 'Released information approved by your clinical team.' : 'Real MRI data and frozen Model 1 results. Clinician validation required.'}</p>
        <div class="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]"><aside class="min-w-0 rounded border bg-[#FFF9EE] p-3"><h3 class="font-bold mb-3">${isPatient ? 'Released studies' : isOrthopedic ? 'Approved cases' : 'Studies'}</h3><div class="space-y-2">${renderStudyList()}</div></aside>
        <main class="min-w-0 space-y-4">${!detail ? '<p>Select an available study.</p>' : `
          <section class="rounded border bg-[#FFF9EE] p-4"><h3 class="font-bold break-all">Study ${escapeHtml(detail.study_id)}</h3><p class="mt-2 font-bold">Workflow: ${escapeHtml(state || detail.status || 'UNINITIALIZED')}</p>
          ${isRadiologist ? `<div class="mt-3 flex gap-4 flex-wrap"><span>Findings review: ${reviewed ? 'FINDINGS REVIEWED' : 'PENDING'}</span><span>Report approval: ${report?.status === 'APPROVED' ? 'RADIOLOGIST APPROVED' : report ? 'DRAFT • PENDING APPROVAL' : 'NOT GENERATED'}</span></div><div class="mt-4 flex flex-wrap gap-2">${button('data-ai-analyze','Analyze AI',!state || state === 'AI_COMPLETE')}${button('data-generate-draft','Generate Draft',state === 'RADIOLOGIST_REVIEW' && reviewed)}${button('data-edit-report','Edit Report',canEdit)}${button('data-approve-report','Approve Report',canEdit && reviewed && !STATE.editingReport)}${button('data-patient-explanation','Generate Patient Explanation',state === 'RADIOLOGIST_APPROVED' && !report?.patient_explanation)}</div>` : ''}
          ${isOrthopedic ? `<div class="mt-3">${button('data-release-patient','Release to Patient',canRelease)}</div><p class="text-sm mt-2">Release requires a signed report, reviewed patient explanation, explicit patient-information approval, and patient linkage.</p>` : ''}</section>
          ${!isPatient ? '<section class="rounded border bg-[#FFF9EE] p-4"><h3 class="font-bold mb-2">MRI • actual DICOM preview</h3><div id="mri-image"></div><p class="text-xs mt-2">Display preview only. Model preprocessing and probabilities are unchanged.</p></section>' : ''}
          ${isRadiologist ? renderAiResults(detail) : ''}
          ${isRadiologist ? `<section class="rounded border bg-[#FFF9EE] p-4"><h3 class="font-bold mb-3">Radiologist finding validation</h3><fieldset ${state !== 'AI_COMPLETE' ? 'disabled' : ''}>${renderReviewCard(detail)}</fieldset>${state !== 'AI_COMPLETE' ? '<p class="text-sm mt-2">Saved decisions are read-only at this workflow stage.</p>' : ''}</section>` : ''}
          ${report ? renderReport(report.draft_content, report.status) : ''}
          ${isRadiologist && STATE.editingReport && canEdit ? renderEditor(report) : ''}
          ${isRadiologist && detail.versions ? `<details class="rounded border bg-white p-3"><summary>Report version history</summary>${detail.versions.map(v => `<p class="mt-2">v${v.version_number} • ${v.version_number === 1 ? 'LLM generated' : 'Radiologist edited'} • ${escapeHtml(v.status)}${report.approved_version === v.version_number ? ' • Signed version' : ''}</p>`).join('')}</details>` : ''}
          ${!isPatient && report?.patient_explanation ? `<h3 class="font-bold">Patient explanation • ${detail.orthopedic_review?.patient_information_approved ? 'APPROVED FOR RELEASE' : 'REQUIRES DOWNSTREAM REVIEW'}</h3>${renderExplanation(report.patient_explanation)}` : ''}
          ${isOrthopedic && state === 'RADIOLOGIST_APPROVED' ? `<section class="rounded border bg-[#FFF9EE] p-4"><h3 class="font-bold mb-3">Orthopedic assessment • separate from signed report</h3>${renderOrthopedicReviewCard(detail)}</section>` : ''}
          ${!isPatient && detail.orthopedic_review ? `<section class="rounded border bg-white p-4"><h3 class="font-bold">Saved orthopedic review</h3><p>Assessment: ${escapeHtml(detail.orthopedic_review.assessment)}</p><p>Recommendation: ${escapeHtml(detail.orthopedic_review.recommendation)}</p><p>Internal notes: ${escapeHtml(detail.orthopedic_review.notes || 'None')}</p><p>Patient information approved: ${detail.orthopedic_review.patient_information_approved ? 'YES' : 'NO'}</p><p>Approved follow-up: ${escapeHtml(detail.orthopedic_review.approved_followup_info || 'None')}</p></section>` : ''}
          ${isPatient ? `${renderReport(detail.approved_report, 'APPROVED')}${renderExplanation(detail.patient_explanation)}<section class="rounded border bg-white p-4"><h3 class="font-bold">Approved follow-up information</h3><p>${escapeHtml(detail.approved_followup_info || 'No additional follow-up information released.')}</p></section>` : ''}
        `}</main></div></div>`;
      shell.querySelector('#logout-button').onclick = logout;
      shell.querySelectorAll('[data-select-study]').forEach(b => b.onclick = async () => {STATE.selectedStudyId = b.dataset.selectStudy; STATE.editingReport = false; STATE.aiMetadata = null; await refreshStudyDetail();});
      const actions = {'[data-ai-analyze]':runAiAnalysis, '[data-generate-draft]':generateDraft, '[data-edit-report]':editReport, '[data-approve-report]':approveReport, '[data-patient-explanation]':generatePatientExplanation, '[data-release-patient]':releaseToPatient, '#review-form':submitReview, '#orthopedic-review-form':submitOrthopedicReview, '#report-editor':saveReport};
      Object.entries(actions).forEach(([selector, handler]) => shell.querySelectorAll(selector).forEach(el => el.addEventListener(el.tagName === 'FORM' ? 'submit' : 'click', handler)));
      shell.querySelector('[data-cancel-edit]')?.addEventListener('click', () => {STATE.editingReport = false; render();});
      (detail?.validated_findings || []).forEach(f => {const i = CANONICAL_ORDER.indexOf(f.finding); const el = shell.querySelector(`[name="outcome-${i}"]`); if (el) el.value = f.outcome === 'APPROVED' ? 'CONFIRMED' : f.outcome; const input = shell.querySelector(`[name="details-${i}"]`); if(input) input.value = f.details || '';});
      if (STATE.submitting) shell.querySelectorAll('button,input,select,textarea').forEach(el => el.disabled = true);
      if (!isPatient && detail) { if (STATE.mri?.studyId === detail.study_id) drawMri(); else if (!STATE.loading) loadMri(); }
    }

''' +s[end:]
p.write_text(s)
