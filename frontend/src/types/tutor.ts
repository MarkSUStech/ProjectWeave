/** Tutor 契约（镜像 backend/app/domains/tutor/schemas.py）。 */
import { z } from 'zod'

export const workspaceActionSchema = z.object({
  kind: z.enum(['display-notice', 'switch-layout', 'propose-patch']),
  level: z.enum(['A0', 'A1', 'A2']),
  reason: z.string(),
  payload: z.record(z.string(), z.unknown()),
})

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
  workspaceActions: z.array(workspaceActionSchema).default([]),
  // P6 Agent 工具调用轨迹（真实后端执行记录）
  toolCalls: z.array(z.object({
    tool: z.string(),
    args: z.record(z.string(), z.unknown()).default({}),
    ok: z.boolean(),
    round: z.number().int(),
    durationMs: z.number().int().default(0),
    summary: z.string().default(''),
    error: z.string().nullable().default(null),
  })).default([]),
  agentRounds: z.number().int().default(0),
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
export type WorkspaceAction = z.infer<typeof workspaceActionSchema>
