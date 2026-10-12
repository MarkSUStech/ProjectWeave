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
  description: z.string().default(''),
  requiredConcepts: z.array(z.string()).default([]),
  deliverable: z.string().default(''),
  testFiles: z.array(z.string()).default([]),
  // P8.2：CMake 任务验收契约（按构建目标/CTest 名验收；空 = 旧 testFiles 语义）
  verification: z.object({
    buildSystem: z.string(),
    buildTargets: z.array(z.string()).default([]),
    testNames: z.array(z.string()).default([]),
    verificationProfile: z.string().default('ctest'),
  }).nullish(),
  acceptanceCriteria: z.array(z.string()).default([]),
  dependsOn: z.array(z.string()).default([]),
  // P5.1：任务级渐进提示与可视化教学建议
  hints: z.array(z.object({ level: z.number().int(), text: z.string() })).default([]),
  vizSuggestion: z.string().default(''),
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
