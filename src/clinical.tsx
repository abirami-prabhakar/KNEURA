import { useState } from 'react'
import type { CSSProperties } from 'react'
import type { Case, Finding, Role } from './types'
import { StatusBadge } from './components'

import { probabilityLabel } from './workflow'

// URLs are backend-rendered images. No pixel processing or attribution is performed here.
export function ClinicalImage({ src, label, style }: { src?: string; label: string; style?: CSSProperties }) {
  return <ImageResource key={src || 'unavailable'} src={src} label={label} style={style}/>
}

function ImageResource({ src, label, style }: { src?: string; label: string; style?: CSSProperties }) {
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [attempt, setAttempt] = useState(0)
  return <div className="clinical-image" aria-busy={Boolean(src) && state === 'loading'}>
    {!src ? <p className="image-message">{label} unavailable.</p> : <>
      {state === 'loading' && <p className="image-message" role="status">Loading {label}…</p>}
      {state === 'error' ? <div className="image-message" role="alert"><p>{label} unavailable. The image could not be loaded.</p><button className="button" onClick={() => { setState('loading'); setAttempt(value => value + 1) }}>Retry image</button></div> :
        <img key={attempt} src={src} alt={label} style={{ ...style, visibility: state === 'ready' ? 'visible' : 'hidden' }} onLoad={() => setState('ready')} onError={() => setState('error')}/>}
    </>}
  </div>
}

export function EvidenceCard({ item, finding, role, onOpen }: { item: Case; finding: Finding; role: Role; onOpen?: () => void }) {
  const evidence = finding.evidence
  if (role === 'patient') return null
  return <section className="evidence-card" aria-label={`Evidence card for ${finding.name}`}>
    <header><div><span className="eyebrow">{role === 'radiologist' ? 'AI FINDING / EVIDENCE CARD' : 'APPROVED FINDING / EVIDENCE'}</span><h3>{finding.name}</h3></div><StatusBadge status={finding.status}/></header>
    <dl className="evidence-metadata">
      {role === 'radiologist' && <div><dt>AI probability</dt><dd>{probabilityLabel(finding.probability)}</dd></div>}
      {role === 'radiologist' && <div><dt>Study probability (as supplied)</dt><dd>{finding.probability ?? 'Unavailable'}</dd></div>}
      {role === 'radiologist' && <div><dt>Selected-window probability</dt><dd>{evidence?.windowProbability ?? 'Unavailable'}</dd></div>}
      <div><dt>MRI series</dt><dd>{evidence?.seriesName || 'Unavailable'}</dd></div>
      <div><dt>Series UID</dt><dd>{evidence?.seriesId || 'Unavailable'}</dd></div>
      <div><dt>Plane</dt><dd>{evidence?.plane || item.series.find(series => series.id === evidence?.seriesId)?.plane || 'Unavailable'}</dd></div>
      <div><dt>Evidence window index</dt><dd>{evidence?.windowNumber ?? 'Unavailable'}</dd></div>
      <div><dt>Five InstanceNumbers</dt><dd>{evidence?.instanceNumbers?.length ? evidence.instanceNumbers.join(', ') : 'Unavailable'}</dd></div>
      <div><dt>Slice range</dt><dd>{evidence?.sliceStart != null && evidence.sliceEnd != null ? `${evidence.sliceStart}–${evidence.sliceEnd}` : 'Unavailable'}</dd></div>
      {role === 'radiologist' && <div><dt>Model version</dt><dd>{evidence?.modelVersion || item.analysis?.modelVersion || 'Unavailable'}</dd></div>}
      {role === 'radiologist' && evidence?.analysisId && <div><dt>Inference reference</dt><dd>{evidence.analysisId}</dd></div>}
      <div><dt>Radiologist decision</dt><dd>{finding.status} · {finding.decision?.userName || 'Reviewer unavailable'}{finding.decision?.timestamp && <time dateTime={finding.decision.timestamp}> · {new Date(finding.decision.timestamp).toLocaleString()}</time>}</dd></div>
    </dl>
    {!evidence ? <p className="clinical-note">Evidence unavailable for this finding.</p> : <>
      <div className="evidence-images"><figure><ClinicalImage src={evidence.mriImageUrl} label={`MRI evidence for ${finding.name}`}/><figcaption>MRI evidence{evidence.sliceStart != null ? ` / Instance ${evidence.sliceStart}` : ''}</figcaption></figure><figure><ClinicalImage src={evidence.gradCamImageUrl} label={`Grad-CAM for ${finding.name}`}/><figcaption>AI-generated Grad-CAM supplied by the backend</figcaption></figure></div>
      {onOpen && <button className="button" onClick={onOpen}>Open evidence in MRI viewer</button>}
      <p className="clinical-note">{evidence.attribution || 'AI-generated explanation of model attention; not ground truth or a diagnosis.'}</p>
    </>}
  </section>
}

export function PatientIdentity({ item }: { item: Case }) {
  const patient = item.patient
  return <span className="patient-identity"><strong>{patient?.name || item.study.patientName || 'Patient name unavailable'}</strong><small>{patient?.age != null ? `${patient.age} years` : 'Age not supplied'} / {patient?.gender || patient?.sex || 'Gender not supplied'}</small></span>
}

export function PatientStudyDetails({ item, role }: { item: Case; role: Role }) {
  const patient = item.patient
  const context = item.clinical_context || patient?.clinical_context
  return <details className="study-details"><summary>Patient & study information</summary>
    <dl className="evidence-metadata">
      <div><dt>Patient</dt><dd>{patient?.name || item.study.patientName || 'Unavailable'}</dd></div>
      <div><dt>Display ID</dt><dd>{patient?.display_id || 'Unavailable'}</dd></div>
      <div><dt>Age</dt><dd>{patient?.age != null ? `${patient.age} years` : 'Not supplied'}</dd></div>
      <div><dt>{patient?.gender ? 'Gender' : 'Sex'}</dt><dd>{patient?.gender || patient?.sex || 'Not supplied'}</dd></div>
      <div><dt>Study</dt><dd>{item.study.description || 'Unavailable'}</dd></div>
      <div><dt>Laterality</dt><dd>{item.study.laterality || 'Not supplied'}</dd></div>
      {role !== 'patient' && <div><dt>Study UID</dt><dd>{item.study.id || 'Unavailable'}</dd></div>}
      <div><dt>Symptoms</dt><dd>{context?.symptoms || 'Not supplied'}</dd></div>
      <div><dt>Medical history</dt><dd>{context?.medical_history || 'Not supplied'}</dd></div>
      <div><dt>Clinical notes</dt><dd>{context?.clinical_notes || 'Not supplied'}</dd></div>
    </dl>
    {role === 'radiologist' && <><h3>Analysis provenance</h3><dl className="evidence-metadata">
      <div><dt>Model version</dt><dd>{item.analysis?.modelVersion || 'Unavailable'}</dd></div>
      <div><dt>Series evaluated</dt><dd>{item.analysis?.seriesEvaluated ?? 'Unavailable'}</dd></div>
      <div><dt>Windows evaluated</dt><dd>{item.analysis?.windowsEvaluated ?? 'Unavailable'}</dd></div>
      <div><dt>Aggregation</dt><dd>{item.analysis?.aggregation || 'Unavailable'}</dd></div>
      <div><dt>Deployed checkpoint SHA-256</dt><dd>{item.analysis?.checkpointSha256 || 'Unavailable'}</dd></div>
    </dl></>}
  </details>
}

export function NoApprovedFindings() {
  return <div className="review-state" role="status"><strong>No AI finding has been approved.</strong><p>The backend permits a draft with no approved findings. Rejected findings will not enter report generation. This does not establish a normal examination; radiologist review and final approval are still required.</p></div>
}

export function FinalizedSummary({ item, role, onReport }: { item: Case; role: Role; onReport: () => void }) {
  if (item.status !== 'FINAL' || item.report?.status !== 'FINAL') return null
  return <section className="finalized-summary" aria-label="Finalized case summary"><div><span className="eyebrow">FINAL REPORT / RADIOLOGIST VERIFIED</span><h2>{role === 'orthopedist' && !item.releasedToPatient ? 'Awaiting your approval' : 'Review complete'}</h2><p>{item.report.approvedBy || 'Approving radiologist unavailable'}{item.report.approvedAt ? ` · ${new Date(item.report.approvedAt).toLocaleString()}` : ''}</p></div><div className="finalized-counts">
    {role === 'radiologist' && <span><strong>{item.findings.length}</strong> AI-proposed findings</span>}
    <span><strong>{item.findings.filter(f => f.status === 'APPROVED').length}</strong> Radiologist-approved</span>
    {role === 'radiologist' && <span><strong>{item.findings.filter(f => f.status === 'REJECTED').length}</strong> Rejected / excluded from report</span>}
  </div><button className="button" onClick={onReport}>View final report</button>
  {item.releasedToPatient && <span className="small-tag" style={{marginLeft: 'auto'}}>RELEASED TO PATIENT</span>}
  </section>
}
