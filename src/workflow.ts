import type { Finding, Image } from './types'

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
