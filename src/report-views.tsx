import { useState } from 'react'
import type { Case, PatientSummary } from './types'
import { api } from './api'
import { ErrorState, Icon, StatusBadge } from './components'
import { PatientIdentity } from './clinical'

const readableDate = (value?: string) => value ? new Date(value).toLocaleString() : 'Not recorded'
const message = (error: unknown) => error instanceof Error ? error.message : 'The report could not be saved. Try again.'

function ClinicalDocument({ item }: { item: Case }) {
  return <article className="document-paper clinical-report printable-report" aria-label="Clinical report">
    <div className="eyebrow">CLINICAL REPORT / RADIOLOGIST FINALIZED</div>
    <h2>{item.study.description}</h2><PatientIdentity item={item}/>
    <p className="document-meta">Case ID: {item.id} · Patient ID: {item.study.patientId}</p>
    <section><h3>Clinical impression</h3><p className="report-text">{item.report?.impression}</p></section>
    <section><h3>Detailed findings</h3><p className="report-text">{item.report?.findings}</p></section>
    <p className="small-copy">Approved by {item.report?.approvedBy || 'Radiologist'} · {readableDate(item.report?.approvedAt)}</p>
    <p className="small-copy">The finalized clinical wording is preserved. Review the findings and any uncertainty alongside the MRI evidence and clinical examination.</p>
  </article>
}

function SummaryDocument({ item, summary }: { item: Case; summary: PatientSummary }) {
  return <article className="document-paper patient-summary printable-report" aria-label="Patient-friendly summary">
    <div className="eyebrow">YOUR KNEE MRI / REVIEWED SUMMARY</div>
    <h2>Your knee MRI, explained</h2><PatientIdentity item={item}/>
    <p className="document-meta">Case ID: {item.id} · {item.study.description}</p>
    <section><h3>What was found</h3><p className="report-text">{summary.findings}</p></section>
    <section><h3>What this means for you</h3><p className="report-text">{summary.meaning}</p></section>
    <section><h3>Next steps from your orthopedist</h3><p className="report-text">{summary.nextSteps || 'No next steps have been added. Ask your care team for your plan.'}</p></section>
    <section className="summary-limitation"><h3>What this summary can tell you</h3><p>{summary.limitation}</p></section>
    <p className="small-copy">Reviewed by {summary.reviewedBy} · {readableDate(summary.reviewedAt)} · Summary version {summary.version}</p>
    <p className="small-copy">Your care team can also provide the original clinical report.</p>
  </article>
}

export function CoordinatorReports({ item }: { item: Case }) {
  const [view, setView] = useState<'patient' | 'clinical'>('patient')
  const summary = item.patientSummary?.status === 'RELEASED' ? item.patientSummary : undefined
  return <div className="coordinator-report">
    <div className="case-tabs" aria-label="Report audience">
      <button className={view === 'patient' ? 'active' : ''} onClick={()=>setView('patient')}>Patient-friendly summary</button>
      <button className={view === 'clinical' ? 'active' : ''} onClick={()=>setView('clinical')}>Original clinical report</button>
    </div>
    {view === 'patient' ? summary ? <>
      <div className="report-actions"><a className="button" href={api.patientSummaryExportUrl(item.id)} download>Download patient summary</a><button className="button primary" onClick={()=>window.print()}>Print / Save patient summary PDF</button></div>
      <SummaryDocument item={item} summary={summary}/>
    </> : <section className="role-note"><Icon name="clock"/><div><h3>Patient summary awaiting orthopedist review</h3><p>The clinical report is available in the other tab. An orthopedist must prepare and review the simpler summary before it can be shared.</p></div></section> : <>
      <div className="report-actions"><a className="button" href={api.exportUrl(item.id)} download>Export clinical report (JSON)</a><button className="button" onClick={()=>window.print()}>Print / Save clinical report PDF</button></div>
      <ClinicalDocument item={item}/>
    </>}
  </div>
}

export function OrthopedistReports({ item, onChange, onEvidence }: { item: Case; onChange: (item: Case)=>void; onEvidence: (id: string)=>void }) {
  return <div className="audience-reports">
    <ClinicalDocument item={item}/>
    <section className="approved-panel clinical-evidence"><div className="eyebrow">SUPPORTING EVIDENCE</div><h3>Radiologist-approved findings</h3>
      {item.findings.filter(f=>f.status==='APPROVED').map(f=><button className="approved-finding" key={f.id} onClick={()=>onEvidence(f.id)}>{f.name}<Icon name="arrow" size={16}/></button>)}
      {!item.findings.some(f=>f.status==='APPROVED')&&<p>No computer-assisted findings were approved. This does not establish a normal scan; read the clinical impression.</p>}
      <a className="text-button" href={api.exportUrl(item.id)} download>Export original clinical report</a>
    </section>
    <SummaryEditor key={`${item.id}-${item.patientSummary?.version ?? 'new'}-${item.patientSummary?.sourceFingerprint ?? ''}`} item={item} onChange={onChange}/>
  </div>
}

function SummaryEditor({ item, onChange }: { item: Case; onChange: (item: Case)=>void }) {
  const summary = item.patientSummary
  const [findings, setFindings] = useState(summary?.findings || '')
  const [meaning, setMeaning] = useState(summary?.meaning || '')
  const [nextSteps, setNextSteps] = useState(summary?.nextSteps || '')
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const dirty = findings !== summary?.findings || meaning !== summary?.meaning || nextSteps !== summary?.nextSteps
  const ready = summary && ['REVIEWED', 'RELEASED'].includes(summary.status) && !dirty
  const act = async (action: ()=>Promise<Case>) => {
    setBusy(true); setError('')
    try { onChange(await action()); setConfirmed(false) } catch(err) { setError(message(err)) } finally { setBusy(false) }
  }
  return <section className="summary-editor document-paper" aria-label="Orthopedist approval">
    <div className="eyebrow">PATIENT COMMUNICATION</div><h2>Review the patient-friendly summary</h2>
    <p>Check the summary against the clinical report above. Keep any uncertainty and add only the next steps you want the patient to follow.</p>
    {error&&<ErrorState message={error}/>}
    {!summary ? <><p>The starter explains approved finding labels. It does not translate the radiologist's free-text impression or make treatment recommendations.</p><button className="button primary" disabled={busy} onClick={()=>void act(()=>api.preparePatientSummary(item.id))}>Prepare patient summary</button></> : <>
      <p className="small-copy">{summary.status === 'DRAFT' ? 'Draft — not available to the coordinator' : `Reviewed by ${summary.reviewedBy} · ${readableDate(summary.reviewedAt)}`}</p>
      <fieldset disabled={busy} className="summary-fields">
        <label>What was found<textarea aria-label="Patient summary findings" rows={6} maxLength={12000} value={findings} onChange={e=>{setFindings(e.target.value);setConfirmed(false)}}/></label>
        <label>What this means for the patient<textarea aria-label="Patient summary meaning" rows={4} maxLength={6000} placeholder="Explain the clinical impression in everyday language, preserving uncertainty." value={meaning} onChange={e=>{setMeaning(e.target.value);setConfirmed(false)}}/></label>
        <label>Next steps from the orthopedist (optional)<textarea aria-label="Patient summary next steps" rows={3} maxLength={6000} placeholder="Enter your own follow-up plan. No treatment advice is generated." value={nextSteps} onChange={e=>{setNextSteps(e.target.value);setConfirmed(false)}}/></label>
        <p className="clinical-note">{summary.limitation}</p>
        <label className="summary-confirm"><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>I checked this summary against the final report, including uncertainty and next steps.</label>
      </fieldset>
      <div className="report-actions"><button className="button" disabled={busy || !confirmed || !findings.trim() || !meaning.trim()} onClick={()=>void act(()=>api.reviewPatientSummary(item.id, {findings, meaning, nextSteps, sourceFingerprint:summary.sourceFingerprint, version:summary.version, confirmed}))}>{item.releasedToPatient ? 'Approve and publish updated summary' : 'Save reviewed patient summary'}</button>
      {!item.releasedToPatient&&<button className="button primary" disabled={busy || !ready} onClick={()=>void act(()=>api.releaseToPatient(item.id))}>Approve for Patient Coordinator</button>}</div>
      {!item.releasedToPatient&&<p className="small-copy">Save the reviewed summary before releasing this case. Both the clinical report and the patient summary will become available to the coordinator.</p>}
      {item.releasedToPatient&&ready&&<p role="status">The reviewed patient summary is available to the Patient Coordinator.</p>}
      {dirty&&summary.status!=='DRAFT'&&<p role="status">Unsaved edits. The last reviewed version remains unchanged.</p>}
    </>}
    {item.releasedToPatient&&<StatusBadge status="FINAL"/>}
  </section>
}
