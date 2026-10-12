/**
 * 课程生成 API 客户端（P7.1）：创建/轮询/分析/蓝图/验证/发布。
 */

import { api } from './client'
import { z } from 'zod'

export const COURSE_STATUSES = [
  'pending', 'fetching', 'analyzing', 'scoping', 'generating',
  'validating', 'draft', 'published', 'failed',
] as const
export type CourseStatus = (typeof COURSE_STATUSES)[number]
export const TERMINAL_STATUSES = new Set(['draft', 'published', 'failed'])

export const STAGE_LABELS: Record<string, string> = {
  pending: '排队中',
  fetching: '抓取仓库（元数据/文件树/内容）',
  analyzing: 'AI 分析仓库（工具调用中）',
  scoping: '确定教学范围',
  generating: '生成课程蓝图',
  validating: '确定性验证',
  draft: '蓝图就绪（草稿）',
  published: '已发布',
  failed: '失败',
}

export const evidenceSchema = z.object({
  path: z.string(),
  note: z.string().default(''),
  lines: z.string().default(''),
})

export const claimSchema = z.object({
  statement: z.string(),
  kind: z.enum(['confirmed', 'inferred', 'unknown']),
  sources: z.array(evidenceSchema).default([]),
})

export const analysisSchema = z.object({
  summary: z.string().default(''),
  techStack: z.array(z.string()).default([]),
  entryPoints: z.array(z.string()).default([]),
  modules: z.array(claimSchema).default([]),
  behaviors: z.array(claimSchema).default([]),
  testsSummary: z.string().default(''),
  dependencies: z.array(z.string()).default([]),
  limitations: z.array(z.string()).default([]),
  claims: z.array(claimSchema).default([]),
})

export const milestoneSchema = z.object({
  milestoneId: z.string(),
  title: z.string(),
  description: z.string().default(''),
  targetFeatures: z.array(z.string()).default([]),
  deliverables: z.array(z.string()).default([]),
  dependsOn: z.array(z.string()).default([]),
  acceptanceCriteria: z.array(z.string()).default([]),
  estimatedEffortBand: z.string().default('medium'),
})

export const taskSpecSchema = z.object({
  taskId: z.string(),
  milestoneId: z.string(),
  title: z.string(),
  description: z.string().default(''),
  dependsOn: z.array(z.string()).default([]),
  requiredConcepts: z.array(z.string()).default([]),
  learningObjectives: z.array(z.string()).default([]),
  expectedFiles: z.array(z.string()).default([]),
  deliverables: z.array(z.string()).default([]),
  acceptanceCriteria: z.array(z.string()).default([]),
  testStrategy: z.string().default(''),
  hintsOutline: z.array(z.string()).default([]),
  sourceEvidence: z.array(evidenceSchema).default([]),
})

export const knowledgeSchema = z.object({
  conceptId: z.string(),
  title: z.string(),
  description: z.string().default(''),
  prerequisites: z.array(z.string()).default([]),
  relatedTasks: z.array(z.string()).default([]),
  isExisting: z.boolean().default(false),
})

export const blueprintSchema = z.object({
  project: z.object({
    title: z.string(),
    description: z.string().default(''),
    sourceUrl: z.string(),
    commitSha: z.string(),
    license: z.record(z.string(), z.unknown()).default({}),
    techStack: z.array(z.string()).default([]),
    finalArtifact: z.string().default(''),
    targetLevel: z.string().default('beginner'),
    difficulty: z.string().default('medium'),
    goals: z.array(z.string()).default([]),
    nonGoals: z.array(z.string()).default([]),
    runtimeRequirements: z.array(z.string()).default([]),
    evidence: z.array(evidenceSchema).default([]),
  }),
  milestones: z.array(milestoneSchema).min(1),
  tasks: z.array(taskSpecSchema).min(1),
  knowledgeRequirements: z.array(knowledgeSchema).default([]),
  blueprintVersion: z.number().int().default(1),
  generatorVersion: z.string().default(''),
  generationStatus: z.string().default('draft'),
  warnings: z.array(z.string()).default([]),
})

export const validationSchema = z.object({
  passed: z.boolean(),
  issues: z.array(z.object({
    code: z.string(),
    message: z.string(),
    severity: z.enum(['error', 'warning']).default('error'),
    path: z.string().default(''),
  })).default([]),
  checkedAt: z.string(),
})

export const generationSchema = z.object({
  id: z.string().uuid(),
  sourceUrl: z.string(),
  status: z.enum(COURSE_STATUSES),
  stage: z.string().nullable().default(null),
  progress: z.number().int().default(0),
  error: z.string().nullable().default(null),
  warnings: z.array(z.string()).default([]),
  repoOwner: z.string().nullable().default(null),
  repoName: z.string().nullable().default(null),
  commitSha: z.string().nullable().default(null),
  defaultBranch: z.string().nullable().default(null),
  license: z.record(z.string(), z.unknown()).nullable().default(null),
  stats: z.record(z.string(), z.unknown()).nullable().default(null),
  repairRounds: z.number().int().default(0),
  publishedAt: z.string().nullable().default(null),
  createdAt: z.string(),
  updatedAt: z.string(),
})

export type CourseGeneration = z.infer<typeof generationSchema>
export type CourseBlueprint = z.infer<typeof blueprintSchema>
export type RepositoryAnalysis = z.infer<typeof analysisSchema>
export type ValidationInfo = z.infer<typeof validationSchema>
export type TaskSpec = z.infer<typeof taskSpecSchema>
export type MilestoneSpec = z.infer<typeof milestoneSchema>

export async function createCourseGeneration(url: string): Promise<{ id: string }> {
  const data = await api.post<unknown>('/course-generations', { repositoryUrl: url })
  return z.object({ id: z.string().uuid(), status: z.string(), progress: z.number().int() }).parse(data)
}

export async function getCourseGeneration(id: string): Promise<CourseGeneration> {
  return generationSchema.parse(await api.get<unknown>(`/course-generations/${id}`))
}

export async function getCourseAnalysis(id: string): Promise<{
  analysis: RepositoryAnalysis | null
  toolCalls: Array<{ tool: string; ok: boolean; args: Record<string, unknown> }>
}> {
  const data = await api.get<unknown>(`/course-generations/${id}/analysis`)
  return z.object({
    status: z.string(),
    analysis: analysisSchema.nullable().default(null),
    toolCalls: z.array(z.object({
      tool: z.string(), ok: z.boolean(),
      args: z.record(z.string(), z.unknown()).default({}),
    })).default([]),
  }).parse(data)
}

export async function getCourseBlueprint(id: string): Promise<{
  blueprint: CourseBlueprint | null
  validation: ValidationInfo | null
}> {
  const data = await api.get<unknown>(`/course-generations/${id}/blueprint`)
  return z.object({
    status: z.string(),
    blueprint: blueprintSchema.nullable().default(null),
    validation: validationSchema.nullable().default(null),
  }).parse(data)
}

export async function publishCourseGeneration(id: string): Promise<{
  taskCount: number
  milestoneCount: number
}> {
  const data = await api.post<unknown>(`/course-generations/${id}/publish`)
  return z.object({
    id: z.string(), status: z.string(), publishedAt: z.string().nullable(),
    taskCount: z.number().int(), milestoneCount: z.number().int(),
  }).parse(data)
}

export async function retryCourseGeneration(id: string): Promise<CourseGeneration> {
  return generationSchema.parse(await api.post<unknown>(`/course-generations/${id}/retry`))
}


// ---------------------------------------------------------------- P7.2 课程内容/发布

export const artifactSchema = z.object({
  taskId: z.string(),
  milestoneId: z.string(),
  language: z.string(),
  instructions: z.object({
    title: z.string(),
    context: z.string().default(''),
    goal: z.string().default(''),
    requiredConcepts: z.array(z.string()).default([]),
    features: z.array(z.string()).default([]),
    expectedFiles: z.array(z.string()).default([]),
    ioBehavior: z.string().default(''),
    constraints: z.array(z.string()).default([]),
    acceptance: z.array(z.string()).default([]),
    relationToPrev: z.string().default(''),
    relationToNext: z.string().default(''),
  }),
  starterFiles: z.array(z.object({ path: z.string(), content: z.string() })).default([]),
  testFiles: z.array(z.object({ path: z.string(), content: z.string() })).default([]),
  hints: z.array(z.object({ level: z.number().int(), text: z.string() })).default([]),
  status: z.string(),
  verifications: z.array(z.object({
    kind: z.string(), status: z.string(),
    exitCode: z.number().int().nullable().default(null),
    totalTests: z.number().int().default(0), passedTests: z.number().int().default(0),
    failedTests: z.number().int().default(0),
    diagnostics: z.array(z.record(z.string(), z.unknown())).default([]),
    stdoutTail: z.string().default(''),
    stderrTail: z.string().default(''),
    durationMs: z.number().int().default(0),
  })).default([]),
  repairs: z.array(z.object({
    round: z.number().int(), problem: z.string(),
    changedFiles: z.array(z.string()).default([]), outcome: z.string(),
  })).default([]),
  error: z.string().nullable().default(null),
})

export const releaseSchema = z.object({
  id: z.string().uuid(),
  generationId: z.string().uuid(),
  releaseVersion: z.number().int(),
  status: z.enum(['generating', 'verifying', 'ready', 'failed']),
  language: z.string(),
  totalTasks: z.number().int().default(0),
  passedTasks: z.number().int().default(0),
  failedTasks: z.number().int().default(0),
  progress: z.number().int().default(0),
  currentTask: z.string().nullable().default(null),
  error: z.string().nullable().default(null),
  courseTitle: z.string().default(''),
  readyAt: z.string().nullable().default(null),
  createdAt: z.string(),
})

export const releaseDetailSchema = releaseSchema.extend({
  artifacts: z.array(artifactSchema).default([]),
})

export type CourseRelease = z.infer<typeof releaseSchema>
export type ReleaseDetail = z.infer<typeof releaseDetailSchema>
export type LessonArtifact = z.infer<typeof artifactSchema>

export async function buildLessons(generationId: string): Promise<CourseRelease> {
  return releaseSchema.parse(await api.post<unknown>(
    `/course-generations/${generationId}/build-lessons`))
}

export async function getRelease(id: string): Promise<ReleaseDetail> {
  return releaseDetailSchema.parse(await api.get<unknown>(`/course-releases/${id}`))
}

export async function instantiateRelease(
  id: string, title?: string,
): Promise<{ projectId: string; firstTaskId: string | null }> {
  const data = await api.post<unknown>(`/course-releases/${id}/instantiate`,
    title ? { projectTitle: title } : undefined)
  return z.object({
    projectId: z.string().uuid(), firstTaskId: z.string().nullable(),
  }).parse(data)
}


// ---------------------------------------------------------------- P7.3 学习生命周期

export const lifecycleTaskSchema = z.object({
  taskId: z.string(),
  status: z.enum(['locked', 'available', 'active', 'needs-fix', 'completed']),
  dependsOn: z.array(z.string()).default([]),
  milestone: z.number().int(),
  title: z.string(),
})

export const courseProgressSchema = z.object({
  courseMode: z.boolean(),
  releaseId: z.string().nullable().default(null),
  releaseVersion: z.number().int().default(0),
  currentTask: z.string().nullable().default(null),
  completedCount: z.number().int().default(0),
  totalCount: z.number().int().default(0),
  allCompleted: z.boolean().default(false),
  tasks: z.array(lifecycleTaskSchema).default([]),
})

export type CourseProgress = z.infer<typeof courseProgressSchema>

export async function getCourseProgress(projectId: string): Promise<CourseProgress> {
  return courseProgressSchema.parse(
    await api.get<unknown>(`/projects/${projectId}/course-progress`))
}

export interface ActivateResult {
  activated: boolean
  alreadyActive?: boolean
  filesCreated?: string[]
  filesUpdated?: string[]
  conflicts?: Array<{ path: string; reason: string; suggestion: string }>
  message?: string
}

export async function activateTask(projectId: string, taskId: string): Promise<ActivateResult> {
  const data = await api.post<unknown>(`/projects/${projectId}/tasks/${taskId}/activate`, {})
  return data as ActivateResult
}
