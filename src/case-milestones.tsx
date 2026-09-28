import type { Case } from './types'
import { reviewComplete } from './workflow'

export function CaseMilestones({ item }: { item: Case }) {
  const reviewed = item.findings.filter(f => f.status !== 'PENDING').length
  const complete = reviewComplete(item.findings)
  const finalized = item.status === 'FINAL' && item.report?.status === 'FINAL'
  const stages = [
    { label: 'MRI received', done: true, detail: `${item.series.length} series` },
    { label: 'AI analysis', done: item.findings.length === 12, detail: item.status==='ERROR'?'Analysis failed; retry required':`${item.findings.length}/12 outputs available` },
    { label: 'Radiologist review', done: complete, detail: `${reviewed}/12 reviewed` },
    { label: 'Report draft', done: Boolean(item.report), detail: item.report ? 'Draft generated' : 'Awaiting review' },
    { label: 'Final approval', done: finalized, detail: finalized ? item.report?.approvedBy || 'Approved' : 'Awaiting sign-off' },
  ]
  const current = stages.findIndex(stage => !stage.done)
  return <ol className="case-milestones" aria-label="Case workflow milestones">{stages.map((stage, index) =>
    <li key={stage.label} className={stage.done ? 'complete' : index === current ? 'current' : ''} aria-current={index === current ? 'step' : undefined}>
      <span className="milestone-number" aria-hidden="true">{stage.done ? '✓' : index + 1}</span>
      <div><strong>{stage.label}</strong><small>{stage.detail}</small></div>
    </li>)}</ol>
}
