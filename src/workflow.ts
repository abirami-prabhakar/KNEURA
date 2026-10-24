import type { Case, Finding, Image, Report, Role } from './types'

export function needsAttention(item: Case, role: Role): boolean {
  if (role === 'orthopedist') return item.status === 'FINAL' && item.report?.status === 'FINAL' && !item.releasedToPatient
  return role === 'radiologist' && ['AI_READY', 'REVIEWING', 'ERROR'].includes(item.status)
}

const names = ['ACL', 'MCL', 'Medial Meniscus', 'Lateral Meniscus', 'Medial OA', 'Lateral OA', 'Patellofemoral OA', 'Effusion', 'Synovitis', "Baker's cyst", 'Contusion', 'Fracture']
const normalize = (name: string) => name.replaceAll('’', "'").toLowerCase()
export function reviewComplete(findings: Finding[]): boolean {
  return findings.length === 12 && new Set(findings.map(f => f.id)).size === 12 && names.every(name => findings.some(f => normalize(f.name) === normalize(name))) && findings.every(f => f.status === 'APPROVED' || f.status === 'REJECTED')
}
export function approvedFindingIds(findings: Finding[]): string[] {
  if (!reviewComplete(findings)) throw new Error('All 12 canonical findings must be reviewed before report generation.')
  return findings.filter(f => f.status === 'APPROVED').map(f => f.id)
}

// Match the inference pipeline: consecutive, overlapping five-image windows.
export function imagingWindows(images: Image[]): Image[][] {
  const ordered = [...images].sort((a, b) => a.instanceNumber - b.instanceNumber)
  return Array.from({ length: Math.max(0, ordered.length - 4) }, (_, index) => ordered.slice(index, index + 5))
}

export function probabilityLabel(value?: number) {
  return typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : 'Unavailable'
}

export function finalApprovalBlocker(report: Report | undefined, findings: Finding[], draft: { findings: string; impression: string }): string | null {
  if (!report) return 'Generate a draft report first.'
  if (report.status === 'FINAL') return 'This report is already finalized.'
  if (!reviewComplete(findings)) return 'Approve or reject all 12 findings before final approval.'
  if (!draft.findings.trim()) return 'Enter the report findings before saving.'
  if (!draft.impression.trim() || draft.impression.trim() === 'Radiologist interpretation required before final approval.') return 'Enter your clinical impression in the Impression field, then save your review.'
  if (draft.findings !== report.findings || draft.impression !== report.impression) return 'Save your changes before final approval.'
  if (report.status !== 'UNDER_REVIEW' || !report.reviewedAt) return 'Review the findings and impression, then select Save reviewed report.'
  return null
}
