/**
 * 项目领域的前端类型契约（与后端 Pydantic 契约镜像，见
 * backend/app/domains/projects/schemas.py）。所有 API 响应先经 zod
 * 校验再进入组件，保证类型安全与运行时契约一致。
 */
import { z } from 'zod'

export const projectModeSchema = z.enum(['rebuild', 'contribution'])
export const projectStatusSchema = z.enum([
  'draft',
  'analyzing',
  'active',
  'completed',
  'archived',
])
export const projectComplexitySchema = z.enum(['small', 'medium', 'large'])
export const milestoneStatusSchema = z.enum(['pending', 'in-progress', 'done'])

export const milestoneSchema = z.object({
  id: z.string(),
  title: z.string(),
  description: z.string().default(''),
  status: milestoneStatusSchema.default('pending'),
})

export const projectReadSchema = z.object({
  id: z.string().uuid(),
  ownerId: z.string(),
  title: z.string(),
  description: z.string(),
  mode: projectModeSchema,
  status: projectStatusSchema,
  complexity: projectComplexitySchema,
  targetFeatures: z.array(z.string()),
  nonGoals: z.array(z.string()),
  stack: z.array(z.string()),
  milestones: z.array(milestoneSchema),
  acceptanceCriteria: z.array(z.string()),
  specVersion: z.number().int(),
  createdAt: z.string(),
  updatedAt: z.string(),
})

export const projectListSchema = z.object({
  items: z.array(projectReadSchema),
  total: z.number().int(),
})

export type ProjectMode = z.infer<typeof projectModeSchema>
export type ProjectStatus = z.infer<typeof projectStatusSchema>
export type ProjectComplexity = z.infer<typeof projectComplexitySchema>
export type Milestone = z.infer<typeof milestoneSchema>
export type Project = z.infer<typeof projectReadSchema>

/** 创建项目的请求体（字段名与后端 camelCase 契约一致）。 */
export interface ProjectCreateInput {
  title: string
  description?: string
  mode?: ProjectMode
  complexity?: ProjectComplexity
  targetFeatures?: string[]
  nonGoals?: string[]
  stack?: string[]
  acceptanceCriteria?: string[]
}
