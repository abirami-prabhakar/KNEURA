import { useState } from 'react'
import lock from '../01_MODEL/KNEE_AI_3_3_MODEL_REPRODUCIBILITY_LOCK.json'
import performance from '../02_PERFORMANCE/KNEE_AI_3_3_PERFORMANCE_EVIDENCE.json'
import provenance from '../03_MRI_PROVENANCE/KNEE_AI_3_3_MRI_DATA_PROVENANCE.json'
import contract from '../04_BACKEND/KNEE_AI_BACKEND_ADAPTER_CONTRACT.json'
import golden from '../05_GOLDEN_CASE/KNEE_AI_GOLDEN_CASE.json'
import gradcam from '../07_GRADCAM/GRADCAM_ALL_12_RESULTS.json'
import gradcamContract from '../07_GRADCAM/KNEE_AI_GRADCAM_CONTRACT.json'
import patientSchema from '../06_AI_MODULE/KNEE_AI_FINAL_AI_HANDOFF/CONTRACTS/KNEE_AI_PATIENT_DETAILS_SCHEMA.json'
import aiContract from '../06_AI_MODULE/KNEE_AI_FINAL_AI_HANDOFF/CONTRACTS/KNEE_AI_FINAL_AI_BACKEND_HANDOFF.json'
import manifest from '../06_AI_MODULE/KNEE_AI_FINAL_AI_HANDOFF/INTEGRATION/INTEGRATION_MANIFEST.json'
import validationSummary from '../06_AI_MODULE/KNEE_AI_FINAL_AI_HANDOFF/VALIDATION/VALIDATION_SUMMARY.json'
import consistency from '../04_BACKEND/KNEE_AI_3_3_FINAL_HANDOFF_CONSISTENCY.json'
import { ClinicalImage } from './clinical'

const overlays = import.meta.glob('../07_GRADCAM/VISUALIZATIONS/*.png', { eager: true, query: '?url', import: 'default' }) as Record<string, string>
const classes = lock.model.class_order

function SourceDetails({ title, value }: { title: string; value: unknown }) {
  return <details className="source-details"><summary>{title} / supplied properties</summary><pre>{JSON.stringify(value, null, 2)}</pre></details>
}

export function HandoffMetadata({ kind }: { kind: 'model' | 'validation' }) {
  return <section className="evidence-card" aria-label="AI team handoff metadata"><div className="eyebrow">SUPPLIED AI TEAM EVIDENCE</div>
    <h2>{kind === 'model' ? 'Frozen model contract' : 'Reported validation results'}</h2>
    <p className="clinical-note">Source: {kind === 'model' ? '01_MODEL / Model reproducibility lock' : '02_PERFORMANCE / Performance evidence'}. These are supplied reference results, not a new evaluation of this deployment.</p>
    {kind === 'model' ? <dl className="evidence-metadata"><div><dt>Architecture</dt><dd>{lock.model.architecture}</dd></div><div><dt>Input</dt><dd>{lock.model.input_channels} slices / {lock.model.input_size.join(' × ')}</dd></div><div><dt>Original checkpoint SHA-256</dt><dd>{lock.checkpoint.sha256}</dd></div><div><dt>Exact model class order</dt><dd>{classes.join(', ')}</dd></div><div><dt>Grad-CAM target</dt><dd>{gradcamContract.target_layer.module_path}</dd></div><div><dt>Documented AI endpoint</dt><dd>{contract.api.method} {contract.api.endpoint}</dd></div></dl> : <>
      <dl className="evidence-metadata"><div><dt>Studies</dt><dd>{performance.validation_studies}</dd></div><div><dt>Windows</dt><dd>{performance.validation_windows}</dd></div><div><dt>Series</dt><dd>{lock.performance.validation_series}</dd></div><div><dt>Macro AUROC</dt><dd>{performance.macro_auroc}</dd></div><div><dt>Evaluation</dt><dd>{performance.evaluation_method}</dd></div></dl>
      <div className="table-scroll"><table><thead><tr><th>Model class</th><th>Reported study-level AUROC</th></tr></thead><tbody>{classes.map(name=><tr key={name}><td>{name}</td><td>{performance.per_class_auroc[name as keyof typeof performance.per_class_auroc]}</td></tr>)}</tbody></table></div>
    </>}
    <p className="clinical-note">No validated clinical threshold. Radiologist review and final approval remain required.</p>
    {kind === 'model' ? <>
      <SourceDetails title="Model lock, preprocessing and reproducibility" value={lock}/>
      <SourceDetails title="Grad-CAM method, target layer and evidence contract" value={gradcamContract}/>
      <SourceDetails title="Backend adapter contract" value={contract}/>
      <SourceDetails title="AI module integration contract" value={aiContract}/>
      <SourceDetails title="Patient details and clinical context schema" value={patientSchema}/>
      <p className="clinical-note">The supplied original checkpoint hash above is distinct from the deployed checkpoint hash returned by the API. Matching model weights does not establish identical archive hashes.</p>
    </> : <>
      <SourceDetails title="Complete performance evidence" value={performance}/>
      <SourceDetails title="Supplied validation and reproduction checks" value={validationSummary}/>
      <SourceDetails title="Handoff consistency checks" value={consistency}/>
      <SourceDetails title="Integration manifest" value={manifest}/>
    </>}
  </section>
}

export function HandoffStudy() {
  const [selected, setSelected] = useState(0)
  const name = classes[selected]
  const evidence = gradcam.results.find(result => result.class_index === selected && result.abnormality === name)
  const sameStudy = gradcam.study_id === golden.mri.study_instance_uid
  const overlay = evidence && sameStudy ? Object.entries(overlays).find(([path]) => path.split('/').at(-1)?.startsWith(`${String(evidence.class_index).padStart(2, '0')}_`))?.[1] : undefined
  const studyProbability = golden.ai.probabilities[name as keyof typeof golden.ai.probabilities]
  const decision = golden.radiologist_review.approved_findings.includes(name) ? 'APPROVED' : golden.radiologist_review.rejected_findings.includes(name) ? 'REJECTED' : 'PENDING'
  return <>
    <div className="page-intro"><div><div className="eyebrow">CASE DETAILS</div><h1>Radhika</h1><p>{golden.ai.model_version} / {golden.mri.series_evaluated} series / {golden.mri.windows_evaluated} windows / {classes.length} outputs</p></div></div>
    <p className="small-copy">Read-only reference case. Review decisions are simulated; final approval is pending.</p>
    <section className="evidence-card"><h2>Radhika</h2><p className="small-copy">{golden.patient.display_id}</p><p>{golden.patient.age} years / {golden.patient.sex}</p><dl className="evidence-metadata"><div><dt>Symptoms</dt><dd>{golden.patient.clinical_context.symptoms}</dd></div><div><dt>Medical history</dt><dd>{golden.patient.clinical_context.medical_history}</dd></div><div><dt>Clinical notes</dt><dd>{golden.patient.clinical_context.clinical_notes}</dd></div></dl><p className="small-copy">Study UID: {golden.mri.study_instance_uid}</p></section>
    <div className="clinical-workspace handoff-workspace"><section className="evidence-card" aria-label="Golden case evidence"><div className="eyebrow">SUPPLIED MRI + GRAD-CAM OVERLAY</div><h2>{name}</h2><ClinicalImage src={overlay} label={`Supplied Grad-CAM overlay for ${name}`}/><p className="clinical-note">Class-specific model explanation, not ground truth or a diagnosis. Original DICOM slices and a separate raw MRI image are not included in this package.</p>
      <dl className="evidence-metadata"><div><dt>Study probability (mean)</dt><dd>{studyProbability}</dd></div><div><dt>Selected-window probability</dt><dd>{evidence?.probability ?? 'Unavailable'}</dd></div><div><dt>Plane</dt><dd>{evidence?.plane || 'Unavailable'}</dd></div><div><dt>Series UID</dt><dd>{evidence?.series_instance_uid || 'Unavailable'}</dd></div><div><dt>Window index (as supplied)</dt><dd>{evidence?.window_index ?? 'Unavailable'}</dd></div><div><dt>Five InstanceNumbers</dt><dd>{evidence?.instance_numbers.join(', ') || 'Unavailable'}</dd></div><div><dt>Simulated decision</dt><dd>{decision}</dd></div><div><dt>Model version</dt><dd>{gradcam.model_version}</dd></div></dl>
      <p className="small-copy">Study values: 05_GOLDEN_CASE. Window values and overlays: 07_GRADCAM. Values and zero-based window indexes are displayed unchanged.</p><SourceDetails title="Selected Grad-CAM output, shape and heatmap statistics" value={evidence}/>
    </section><aside className="findings-panel"><div className="findings-header"><div className="eyebrow">FROZEN MODEL ORDER</div><h2>12 AI outputs</h2><p>Supplied study probabilities / simulated decisions</p></div><div className="handoff-findings">{classes.map((finding,index)=><button key={finding} className={`finding-row ${selected===index?'selected':''}`} onClick={()=>setSelected(index)} aria-pressed={selected===index}><span><strong>{finding}</strong><small>{golden.radiologist_review.approved_findings.includes(finding)?'Simulated approval':'Simulated rejection'}</small><small>{golden.ai.probabilities[finding as keyof typeof golden.ai.probabilities]}</small></span></button>)}</div></aside></div>
    <section className="evidence-card"><div className="eyebrow">SUPPLIED MRI PROVENANCE</div><h2>Three eligible series</h2><p>{provenance.input_selection.rule}</p><div className="table-scroll"><table><thead><tr><th>Plane</th><th>Series UID</th><th>Windows</th></tr></thead><tbody>{provenance.series.map(series=><tr key={series.SeriesInstanceUID}><td>{series.Anatomical_Plane}</td><td>{series.SeriesInstanceUID}</td><td>{series.windows}</td></tr>)}</tbody></table></div><SourceDetails title="MRI selection, windowing and preprocessing provenance" value={provenance}/></section>
    <section className="evidence-card" aria-label="Supplied draft report"><div className="eyebrow">SIMULATED APPROVED FINDINGS ONLY / DRAFT</div><h2>Reference report</h2><p>{golden.radiologist_review.approved_findings.join(', ')}</p><h3>Findings</h3><p className="report-text">{golden.draft_report.findings.join('\n')}</p><h3>Impression</h3><p>{golden.draft_report.impression}</p><p className="clinical-note">{golden.draft_report.limitations}</p><strong>Final approval: PENDING</strong></section>
    <section className="evidence-card"><h2>Reference workflow provenance</h2><p>{golden.radiologist_review.decision_source}. Reviewer identity and review timestamp are not supplied.</p><SourceDetails title="Simulated review decisions" value={golden.radiologist_review}/><SourceDetails title="Approved-only LLM input and clinical context" value={golden.llm_input}/><SourceDetails title="Draft and final approval properties" value={{ draft: golden.draft_report, final_approval: golden.final_approval }}/><SourceDetails title="Canonical case invariants and source metadata" value={{ status: golden.status, generated_at: golden.generated_at, safety: golden.safety_invariants, integration: golden.integration_invariants }}/></section>
  </>
}
