// Normalize legacy staff labels for display; persisted audit records remain unchanged.
const staffFields = new Set(['actor', 'userName', 'createdBy', 'editedBy', 'approvedBy', 'releasedToPatientBy', 'editor', 'attachedBy'])

export function presentationLabels(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(presentationLabels)
  if (!value || typeof value !== 'object') return value
  const record = value as Record<string, unknown>
  return Object.fromEntries(Object.entries(record).map(([key, field]) => [key,
    typeof field === 'string' && (staffFields.has(key) || (key === 'name' && ['radiologist', 'orthopedist', 'patient'].includes(String(record.role))))
      ? field.replace(/\bdemo\s+/gi, '').trim()
      : presentationLabels(field),
  ]))
}
