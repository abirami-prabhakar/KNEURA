import type { Case } from './types'

export function validatePatient(name: string, age: string, gender: string): Record<string, string> {
  const errors: Record<string, string> = {}
  if (!name.trim()) errors.name = "Please enter the patient's name."
  else if (Array.from(name.trim()).length > 100) errors.name = 'Patient name must be 100 characters or fewer.'
  if (!/^\d+$/.test(age) || Number(age) > 120) errors.age = 'Please enter a valid age between 0 and 120.'
  if (!['Female', 'Male', 'Other', 'Prefer not to say'].includes(gender)) errors.gender = 'Please select a gender.'
  return errors
}

export function patientName(item: Case): string {
  return item.patient?.name || item.study.patientName || 'Patient information unavailable'
}

export function patientDemographics(item: Case): string {
  return [item.patient?.age != null ? `${item.patient.age} years` : '', item.patient?.gender || ''].filter(Boolean).join(' · ')
}
