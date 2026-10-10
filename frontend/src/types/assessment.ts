/** 能力诊断契约（镜像 backend/app/domains/assessments/schemas.py）。 */
import { z } from 'zod'

export const assessmentItemSchema = z.object({
  itemId: z.string(),
  conceptId: z.string(),
  prompt: z.string(),
  options: z.array(z.string()),
  difficulty: z.number().int(),
})

export const conceptResultSchema = z.object({
  conceptId: z.string(),
  label: z.enum(['likely-mastered', 'uncertain', 'likely-gap']),
  correctCount: z.number().int(),
  total: z.number().int(),
})

export const questionResultSchema = z.object({
  itemId: z.string(),
  conceptId: z.string(),
  correct: z.boolean(),
  selectedOptionIndex: z.number().int(),
  correctOptionIndex: z.number().int(),
})

export const assessmentResultsSchema = z.object({
  concepts: z.array(conceptResultSchema),
  questions: z.array(questionResultSchema),
})

export const assessmentSessionSchema = z.object({
  id: z.string().uuid(),
  projectId: z.string().uuid(),
  status: z.enum(['in-progress', 'completed', 'abandoned']),
  items: z.array(assessmentItemSchema),
  results: assessmentResultsSchema.nullable(),
  createdAt: z.string(),
  completedAt: z.string().nullable(),
})

export const assessmentBriefSchema = z.object({
  id: z.string().uuid(),
  status: z.enum(['in-progress', 'completed', 'abandoned']),
  createdAt: z.string(),
  completedAt: z.string().nullable(),
  results: assessmentResultsSchema.nullable(),
})

export const assessmentListSchema = z.object({
  items: z.array(assessmentBriefSchema),
  total: z.number().int(),
})

export type AssessmentItem = z.infer<typeof assessmentItemSchema>
export type ConceptResult = z.infer<typeof conceptResultSchema>
export type QuestionResult = z.infer<typeof questionResultSchema>
export type AssessmentResults = z.infer<typeof assessmentResultsSchema>
export type AssessmentSession = z.infer<typeof assessmentSessionSchema>
export type AssessmentBrief = z.infer<typeof assessmentBriefSchema>
