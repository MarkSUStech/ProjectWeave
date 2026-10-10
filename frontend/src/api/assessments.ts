/** 能力诊断 API。 */

import { api } from './client'
import {
  assessmentListSchema,
  assessmentSessionSchema,
  type AssessmentBrief,
  type AssessmentSession,
} from '../types/assessment'

export interface SubmitAnswer {
  itemId: string
  selectedOptionIndex: number
}

export async function startAssessment(projectId: string): Promise<AssessmentSession> {
  const data = await api.post<unknown>('/assessments/start', { projectId })
  return assessmentSessionSchema.parse(data)
}

export async function submitAssessment(
  sessionId: string,
  answers: SubmitAnswer[],
): Promise<AssessmentSession> {
  const data = await api.post<unknown>(`/assessments/${sessionId}/submit`, { answers })
  return assessmentSessionSchema.parse(data)
}

export async function getAssessment(sessionId: string): Promise<AssessmentSession> {
  const data = await api.get<unknown>(`/assessments/${sessionId}`)
  return assessmentSessionSchema.parse(data)
}

export async function listProjectAssessments(projectId: string): Promise<AssessmentBrief[]> {
  const data = await api.get<unknown>(`/projects/${projectId}/assessments`)
  return assessmentListSchema.parse(data).items
}
