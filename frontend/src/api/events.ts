/** 学习事件 API：批量上报与查询。 */

import { api } from './client'
import {
  eventListSchema,
  ingestResultSchema,
  type LearningEvent,
} from '../types/event'

export interface EventEnvelope {
  eventId: string
  type: string
  occurredAt: string
  aggregateId: string
  projectId?: string
  payload: Record<string, unknown>
}

export async function ingestEvents(events: EventEnvelope[]): Promise<{ accepted: number; duplicated: number }> {
  const data = await api.post<unknown>('/events', { events })
  return ingestResultSchema.parse(data)
}

export async function listEvents(
  projectId?: string,
  type?: string,
): Promise<LearningEvent[]> {
  const params = new URLSearchParams()
  if (projectId) params.set('projectId', projectId)
  if (type) params.set('type', type)
  const query = params.size > 0 ? `?${params.toString()}` : ''
  const data = await api.get<unknown>(`/events${query}`)
  return eventListSchema.parse(data).items
}
