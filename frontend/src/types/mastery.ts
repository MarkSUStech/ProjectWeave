/** 学习者模型契约（镜像 backend/app/domains/learner/schemas.py）。 */
import { z } from 'zod'

export const dimensionEstimateSchema = z.object({
  estimate: z.number().min(0).max(1),
  confidence: z.number().min(0).max(1),
  evidenceCount: z.number().int().positive(),
  lastObservedAt: z.string(),
})

export const masteryReadSchema = z.object({
  conceptId: z.string(),
  dimensions: z.record(z.string(), dimensionEstimateSchema),
  modelVersion: z.string(),
  updatedAt: z.string(),
})

export const masteryListSchema = z.object({
  items: z.array(masteryReadSchema),
  total: z.number().int().nonnegative(),
})

export type DimensionEstimate = z.infer<typeof dimensionEstimateSchema>
export type Mastery = z.infer<typeof masteryReadSchema>
