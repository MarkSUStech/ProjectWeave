/** 阶段任务验收 API（结果由浏览器测试运行器采集后提交）。 */

import { api } from './client'
import { z } from 'zod'

export const evaluationResultSchema = z.object({
  taskId: z.string(),
  status: z.enum(['pending', 'in-progress', 'done', 'needs-fix']),
  passed: z.boolean(),
  rubricVersion: z.string(),
  evidenceConcepts: z.array(z.string()),
  warnings: z.array(z.string()).default([]),
  trustLevel: z.enum(['practice', 'formal']).default('practice'),
})

export type EvaluationResult = z.infer<typeof evaluationResultSchema>

export interface EvaluationFileResult {
  path: string
  status: string
  passed: number
  failed: number
  totalCases: number
}

export interface EvaluationSuiteInput {
  files: EvaluationFileResult[]
  traceId?: string | null
}

export async function evaluateTask(
  projectId: string,
  taskId: string,
  suite: EvaluationSuiteInput,
): Promise<EvaluationResult> {
  const data = await api.post<unknown>(
    `/projects/${projectId}/tasks/${taskId}/evaluate`,
    suite,
  )
  return evaluationResultSchema.parse(data)
}
