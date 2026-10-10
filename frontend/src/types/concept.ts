/**
 * 知识概念契约（镜像 backend/app/domains/concepts/schemas.py）。
 */
import { z } from 'zod'

export const conceptReadSchema = z.object({
  id: z.string(),
  title: z.string(),
  domain: z.string(),
  description: z.string(),
  prerequisites: z.array(z.string()),
  objectives: z.array(z.string()),
  assessmentMethods: z.array(z.string()),
  examples: z.array(z.string()),
  version: z.number().int(),
  updatedAt: z.string(),
})

export const conceptListSchema = z.object({
  items: z.array(conceptReadSchema),
  total: z.number().int().nonnegative(),
  domains: z.array(z.string()),
})

export type Concept = z.infer<typeof conceptReadSchema>
