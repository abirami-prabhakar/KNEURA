export type Role = 'radiologist' | 'orthopedist' | 'patient'
export interface User { id: string; name: string; role: Role }
export interface PatientSummary {
  status: 'DRAFT' | 'REVIEWED' | 'RELEASED'; version: number; sourceFingerprint: string;
  findings: string; meaning: string; nextSteps: string; limitation: string;
  reviewedBy?: string; reviewedAt?: string; sourceReportVersion?: number;
}
export type CaseStatus = 'RECEIVED' | 'PROCESSING' | 'AI_READY' | 'REVIEWING' | 'DRAFT' | 'FINAL' | 'ERROR'
export interface ClinicalContext { symptoms?: string; medical_history?: string; clinical_notes?: string }
export interface PatientDetails { name?: string; gender?: string; patient_id?: string; display_id?: string; age?: number; sex?: string; clinical_context?: ClinicalContext }
export interface Study { id: string; patientName: string; patientId: string; description: string; date: string; laterality?: string; demonstration?: boolean }
export interface Image { id: string; instanceNumber: number; url: string; sourceUrl?: string; width?: number; height?: number; windowWidth?: number; windowCenter?: number }
export interface Series { id: string; name: string; sequence: string; images: Image[]; eligible?: boolean; selectionSource?: string; plane?: string }
export interface Evidence { id?: string; analysisId?: string; generatedAt?: string; modelVersion?: string; seriesId: string; seriesName: string; windowNumber: number; sliceStart: number; sliceEnd: number; mriImageUrl: string; gradCamImageUrl?: string; attribution?: string; instanceNumbers?: number[]; windowProbability?: number; plane?: string; classIndex?: number }
export interface RadiologistDecision { status: 'APPROVED' | 'REJECTED'; userName: string; timestamp: string }
export interface Finding { id: string; name: string; probability?: number; status: 'PENDING' | 'APPROVED' | 'REJECTED'; evidence?: Evidence; decision?: RadiologistDecision; patientExplanation?: string }
export interface Report { id: string; status: 'DRAFT' | 'UNDER_REVIEW' | 'FINAL'; revisions?: { version: number; findings: string; impression: string; updatedAt: string; editor?: string; editorId?: string }[]; editedBy?: string; reviewedAt?: string; findings: string; impression: string; updatedAt: string; approvedBy?: string; approvedAt?: string; statements: { id: string; text: string; findingIds: string[]; source?: 'approved-finding' | 'radiologist-authored' | 'radiologist-linked' | 'llm-context' }[]; provider?: string; version?: number }
export interface AuditEvent { id: string; timestamp: string; action: string; actor: string; caseId?: string; actorId?: string; objectId?: string; previous?: unknown; current?: unknown }
export interface PatientInformation { patientName: string; patientAge: number; patientGender: 'Female' | 'Male' | 'Non-binary' | 'Other' | 'Prefer not to say' }
export interface Patient { name?: string; age?: number | null; gender?: string | null; patient_id?: string; display_id?: string; sex?: string; clinical_context?: ClinicalContext }
export interface Case { patientSummary?: PatientSummary; id: string; createdAt?: string; study: Study; status: CaseStatus; updatedAt: string; series: Series[]; findings: Finding[]; report?: Report; reportJob?: {id:string; status:'QUEUED'|'PROCESSING'|'COMPLETED'|'FAILED';error?:string}; audit: AuditEvent[]; analysisError?: string; patient?: PatientDetails; clinical_context?: ClinicalContext; analysis?: { modelVersion?: string; seriesEvaluated?: number; windowsEvaluated?: number; aggregation?: string; checkpointSha256?: string }; releasedToPatient?: boolean }
export interface ModelMetadata { architecture: string; version: string; checkpoint: string; outputs: number; input: string; limitations: string }
export interface ValidationMetrics { studies: number; windows: number; series: number; macroAuroc: number; evaluatedAt: string; source?: string; limitations?: string }
export const canonicalFindings = ['ACL', 'MCL', 'Medial Meniscus', 'Lateral Meniscus', 'Medial OA', 'Lateral OA', 'Patellofemoral OA', 'Effusion', 'Synovitis', "Baker's cyst", 'Contusion', 'Fracture']
