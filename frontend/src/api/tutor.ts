/** Tutor API。 */

import { api } from './client'
import {
  tutorDecisionListSchema,
  tutorTurnResponseSchema,
  type TutorDecision,
} from '../types/tutor'

export interface TutorTurnExtras {
  currentTaskId?: string
  currentCode?: { path: string; content: string }
  recentRunResult?: { status: string; summary: string }
}

export async function createTutorTurn(
  projectId: string,
  question: string,
  options: { requestAnswerLevel?: boolean; extras?: TutorTurnExtras } = {},
): Promise<TutorDecision> {
  const data = await api.post<unknown>('/tutor/turns', {
    projectId,
    question,
    requestAnswerLevel: options.requestAnswerLevel ?? false,
    ...(options.extras ? { extras: options.extras } : {}),
  })
  return tutorTurnResponseSchema.parse(data).decision
}

/** 主动建议：由后端按介入模式/失败证据/冷却决定是否生成；无建议时返回 null。 */
export async function fetchSuggestion(projectId: string): Promise<TutorDecision | null> {
  const data = await api.get<unknown>(`/tutor/suggestions?projectId=${projectId}`)
  if (data === null) return null
  return tutorTurnResponseSchema.parse(data).decision
}

export async function listTutorDecisions(projectId: string, limit = 10): Promise<TutorDecision[]> {
  const data = await api.get<unknown>(`/tutor/decisions?projectId=${projectId}&limit=${limit}`)
  return tutorDecisionListSchema.parse(data).items
}
