/** 课程规划契约（镜像 backend/app/domains/curriculum/schemas.py）。 */
import { z } from 'zod'

export const planActivitySchema = z.object({
  type: z.enum(['learn-concept', 'practice-task']),
  order: z.number().int().positive(),
  conceptId: z.string().nullable(),
  taskId: z.string().nullable(),
  title: z.string().nullable(),
  reason: z.string(),
})

export const planSkippedSchema = z.object({
  conceptId: z.string(),
  reason: z.string(),
})

export const planReadSchema = z.object({
  id: z.string().uuid(),
  projectId: z.string().uuid(),
  planVersion: z.number().int().positive(),
  activities: z.array(planActivitySchema),
  skipped: z.array(planSkippedSchema),
  reason: z.string(),
  createdAt: z.string(),
})

export const planTaskSchema = z.object({
  taskId: z.string(),
  milestone: z.number().int(),
  title: z.string(),
  status: z.string(),
})

export const planDetailSchema = z.object({
  plan: planReadSchema,
  tasks: z.array(planTaskSchema),
})

export type PlanActivity = z.infer<typeof planActivitySchema>
export type PlanSkipped = z.infer<typeof planSkippedSchema>
export type PlanRead = z.infer<typeof planReadSchema>
export type PlanTask = z.infer<typeof planTaskSchema>
export type PlanDetail = z.infer<typeof planDetailSchema>
