/** 课程规划 API。 */

import { api } from './client'
import { planDetailSchema, planReadSchema, type PlanDetail, type PlanRead } from '../types/plan'

export async function getPlan(projectId: string): Promise<PlanDetail> {
  const data = await api.get<unknown>(`/plans/${projectId}`)
  return planDetailSchema.parse(data)
}

export async function replan(projectId: string): Promise<PlanRead> {
  const data = await api.post<unknown>(`/plans/${projectId}/replan`)
  return planReadSchema.parse(data)
}
