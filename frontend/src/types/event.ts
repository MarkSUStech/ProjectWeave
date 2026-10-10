/** 学习事件契约（镜像 backend/app/domains/events/schemas.py）。 */
import { z } from 'zod'

export const CLIENT_EVENT_TYPES = ['code-run', 'tests-run'] as const
export type ClientEventType = (typeof CLIENT_EVENT_TYPES)[number]

export const eventReadSchema = z.object({
  eventId: z.string(),
  schemaVersion: z.number().int(),
  type: z.string(),
  occurredAt: z.string(),
  aggregateId: z.string(),
  sequence: z.number().int(),
  projectId: z.string().uuid().nullable(),
  payload: z.record(z.string(), z.unknown()),
})

export const eventListSchema = z.object({
  items: z.array(eventReadSchema),
  total: z.number().int(),
})

export const ingestResultSchema = z.object({
  accepted: z.number().int(),
  duplicated: z.number().int(),
})

export type LearningEvent = z.infer<typeof eventReadSchema>
