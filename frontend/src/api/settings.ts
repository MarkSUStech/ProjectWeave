/** 用户 AI 偏好设置 API。 */

import { api } from './client'
import { z } from 'zod'

export const interventionModeSchema = z.enum(['quiet', 'adaptive', 'guided'])
export type InterventionMode = z.infer<typeof interventionModeSchema>

export const MODE_LABELS: Record<InterventionMode, string> = {
  quiet: '安静',
  adaptive: '自适应',
  guided: '引导',
}

export async function getSettings(): Promise<InterventionMode> {
  const data = await api.get<unknown>('/settings')
  return interventionModeSchema.parse(
    (data as { interventionMode: string }).interventionMode,
  )
}

export async function updateSettings(mode: InterventionMode): Promise<InterventionMode> {
  const data = await api.patch<unknown>('/settings', { interventionMode: mode })
  return interventionModeSchema.parse(
    (data as { interventionMode: string }).interventionMode,
  )
}
