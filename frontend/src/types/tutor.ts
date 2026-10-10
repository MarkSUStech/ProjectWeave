/** Tutor 契约（镜像 backend/app/domains/tutor/schemas.py）。 */
import { z } from 'zod'

export const tutorDecisionSchema = z.object({
  id: z.string().uuid(),
  projectId: z.string().uuid(),
  question: z.string(),
  trigger: z.enum(['user', 'auto']),
  intent: z.string(),
  hintLevel: z.number().int().min(0).max(4),
  message: z.string(),
  targetConcepts: z.array(z.string()),
  explanation: z.string(),
  confidence: z.number(),
  outcome: z.string(),
  outcomeReason: z.string(),
  policyVersion: z.string(),
  promptTokens: z.number().int(),
  completionTokens: z.number().int(),
  model: z.string(),
  createdAt: z.string(),
})

export const tutorTurnResponseSchema = z.object({
  decision: tutorDecisionSchema,
})

export const tutorDecisionListSchema = z.object({
  items: z.array(tutorDecisionSchema),
  total: z.number().int(),
})

export type TutorDecision = z.infer<typeof tutorDecisionSchema>
