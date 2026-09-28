import { useEffect, useState } from 'react'
import { api } from './api'
import type { Case, Finding } from './types'
import { EmptyState, StatusBadge } from './components'
import { probabilityLabel } from './workflow'

export function StudySummary({ cases, onOpen }: { cases: Case[]; onOpen: (id: string) => void }) {
  const ordered = [...cases].sort((a,b) => Date.parse(b.updatedAt)-Date.parse(a.updatedAt))
  const active = ordered.find(item => item.status !== 'FINAL') || ordered[0]
  return <section className="evidence-card" aria-label="Active study"><div className="eyebrow">ACTIVE STUDY</div>{active ? <>
    <h2>{active.patient?.display_id || active.id}</h2><p>{active.study.description}</p><dl className="evidence-metadata">
      <div><dt>MRI</dt><dd>{active.series.length ? `${active.series.length} series received` : 'Images unavailable'}</dd></div>
      <div><dt>Analysis status</dt><dd><StatusBadge status={active.status}/></dd></div>
      <div><dt>AI model</dt><dd>{active.analysis?.modelVersion || 'Not supplied'}</dd></div>
      <div><dt>Awaiting review</dt><dd>{active.findings.filter(f=>f.status==='PENDING').length} findings</dd></div>
      <div><dt>Report status</dt><dd>{active.report?.status || 'Not generated'}</dd></div>
    </dl><button className="button primary" onClick={()=>onOpen(active.id)}>Open study</button>
  </> : <EmptyState title="No active study" description="Upload an MRI study to begin analysis and review."/>}</section>
}

export function SystemStatus({ cases }: { cases: Case[] }) {
  const [state, setState] = useState<'checking'|'online'|'offline'>('checking')
  const [attempt, setAttempt] = useState(0)
  useEffect(()=>{let active=true; api.health().then(result=>{if(active)setState(result.status==='ok'?'online':'offline')}).catch(()=>{if(active)setState('offline')});return()=>{active=false}},[attempt])
  const processing=cases.some(c=>c.status==='PROCESSING')
  return <section className="evidence-card" aria-label="System status"><div className="eyebrow">SYSTEM STATUS</div><h2>Workspace services</h2><dl className="service-status">
    <div><dt>API connection</dt><dd>{state==='checking'?'Checking…':state==='online'?'Reachable':'Unavailable'}</dd></div>
    <div><dt>AI engine</dt><dd>{processing?'Analysis in progress':'Readiness not reported'}</dd></div>
    <div><dt>MRI pipeline</dt><dd>{cases.some(c=>c.series.length)?'Study images received':'No study images loaded'}</dd></div>
    <div><dt>Explainability</dt><dd>{cases.some(c=>c.findings.some(f=>f.evidence?.gradCamImageUrl))?'Evidence supplied for loaded studies':'No evidence supplied yet'}</dd></div>
    <div><dt>Reporting</dt><dd>{cases.some(c=>c.report)?'Reports available in worklist':'No reports generated yet'}</dd></div>
  </dl><p className="small-copy">Service readiness is not exposed by the API. Study indicators reflect the loaded worklist.</p><button className="text-button" onClick={()=>{setState('checking');setAttempt(v=>v+1)}}>Refresh status</button></section>
}

export function AnalysisCards({ item, findings, locked, onDecide, onEvidence }: { item: Case; findings: Finding[]; locked: boolean; onDecide: (finding: Finding, status: 'APPROVED'|'REJECTED') => void; onEvidence: (id: string) => void }) {
  return <section aria-label="AI analysis"><div className="analysis-heading"><div className="eyebrow">AI-ASSISTED ANALYSIS / RADIOLOGIST REVIEW REQUIRED</div><h2>{item.analysis?.modelVersion || 'AI'} Analysis</h2><p>{item.analysis?.seriesEvaluated ?? 'Unknown'} series analyzed / {item.analysis?.windowsEvaluated ?? 'Unknown'} inference windows / 5-slice model context</p><StatusBadge status={item.status}/><p>AI probability is an assistive model output and does not constitute a diagnosis.</p><p>{findings.filter(f=>f.status==='APPROVED').length} approved / {findings.filter(f=>f.status==='REJECTED').length} rejected / {findings.filter(f=>f.status==='PENDING').length} pending</p></div>
    {!findings.length && <EmptyState title={item.status==='PROCESSING'?'Analysis in progress':'No AI findings yet'} description="The backend will supply findings after analysis completes."/>}
    <div className="analysis-cards">{findings.map(f=><article className="evidence-card" key={f.id} aria-label={`Analysis ${f.name}`}><h3>{f.name}</h3><span className="eyebrow">AI PROBABILITY</span><strong className="card-probability">{probabilityLabel(f.probability)}</strong>{f.probability != null&&<progress aria-label={`${f.name} AI probability`} value={f.probability} max={1}/>}<StatusBadge status={f.status}/><p>{f.status==='APPROVED'?'Approved for report':f.status==='REJECTED'?'Rejected by radiologist':'Awaiting radiologist review'}</p><button className="text-button" onClick={()=>onEvidence(f.id)}>View explanation</button><div className="decision-actions"><button className="button" disabled={locked} onClick={()=>onDecide(f,'APPROVED')}>Approve</button><button className="button" disabled={locked} onClick={()=>onDecide(f,'REJECTED')}>Reject</button></div></article>)}</div>
  </section>
}
