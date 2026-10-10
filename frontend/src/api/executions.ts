/**
 * 远程执行会话 API（P4.2b）。
 * - POST /executions 创建（202）；GET /executions/{id} 轮询（?afterSeq= 增量）；
 *   POST /executions/{id}/cancel 取消。
 * - 沙箱不可用 → 503（ApiError，前端明确提示，不模拟成功）。
 */

import { api } from './client'
import { z } from 'zod'

export const EXECUTION_STATUSES = [
  'queued',
  'preparing',
  'running',
  'completed',
  'failed',
  'timed-out',
  'cancelled',
] as const

export type ExecutionStatus = (typeof EXECUTION_STATUSES)[number]

export const TERMINAL_STATUSES: ReadonlySet<ExecutionStatus> = new Set([
  'completed',
  'failed',
  'timed-out',
  'cancelled',
])

export const executionEventSchema = z.object({
  seq: z.number().int(),
  at: z.string(),
  channel: z.enum(['stdout', 'stderr', 'system']),
  text: z.string(),
})

export const diagnosticSchema = z.object({
  severity: z.enum(['error', 'warning', 'info']).default('error'),
  message: z.string(),
  file: z.string().nullable().default(null),
  line: z.number().int().nullable().default(null),
  column: z.number().int().nullable().default(null),
  source: z.enum(['build', 'runtime', 'test']).default('runtime'),
})

export const testCaseSchema = z.object({
  name: z.string(),
  status: z.enum(['passed', 'failed', 'error', 'skipped']),
  error: z.string().nullable().default(null),
  file: z.string().nullable().default(null),
  line: z.number().int().nullable().default(null),
  durationMs: z.number().int().default(0),
})

export const testFileSchema = z.object({
  path: z.string(),
  status: z.enum(['passed', 'failed', 'error']),
  cases: z.array(testCaseSchema).default([]),
  error: z.string().nullable().default(null),
})

export const executionSnapshotSchema = z.object({
  id: z.string().uuid(),
  language: z.string(),
  mode: z.enum(['run', 'test']),
  status: z.enum(EXECUTION_STATUSES),
  entryPoint: z.string().nullable().default(null),
  testPaths: z.array(z.string()).default([]),
  timeoutMs: z.number().int(),
  codeFingerprint: z.string().nullable().default(null),
  projectId: z.string().uuid().nullable().default(null),
  exitCode: z.number().int().nullable().default(null),
  timedOut: z.boolean().default(false),
  cancelled: z.boolean().default(false),
  error: z.string().nullable().default(null),
  stdout: z.string().default(''),
  stderr: z.string().default(''),
  events: z.array(executionEventSchema).default([]),
  diagnostics: z.array(diagnosticSchema).default([]),
  testResults: z.array(testFileSchema).nullable().default(null),
  phases: z
    .array(
      z.object({
        name: z.string(),
        status: z.string(),
        durationMs: z.number().int().default(0),
        exitCode: z.number().int().nullable().default(null),
      }),
    )
    .default([]),
  sandbox: z
    .object({
      engine: z.string().nullable().default(null),
      image: z.string().nullable().default(null),
      // 服务端执行 ≠ 正式认证（D32）：本阶段结果一律 practice
      trustLevel: z.enum(['practice', 'formal']).default('practice'),
    })
    .default({ engine: null, image: null, trustLevel: 'practice' }),
  queuedAt: z.string(),
  startedAt: z.string().nullable().default(null),
  finishedAt: z.string().nullable().default(null),
  runTimeMs: z.number().int().default(0),
})

export type ExecutionSnapshot = z.infer<typeof executionSnapshotSchema>
export type RemoteDiagnostic = z.infer<typeof diagnosticSchema>
export type RemoteTestCase = z.infer<typeof testCaseSchema>
export type RemoteTestFile = z.infer<typeof testFileSchema>

export interface CreateExecutionInput {
  language: string
  mode: 'run' | 'test'
  entryPoint?: string
  testPaths?: string[]
  files: Record<string, string>
  stdin?: string
  timeoutMs?: number
  codeFingerprint?: string
  projectId?: string
}

export async function createExecution(input: CreateExecutionInput): Promise<{ id: string; status: ExecutionStatus }> {
  const data = await api.post<unknown>('/executions', input)
  return z.object({ id: z.string().uuid(), status: z.enum(EXECUTION_STATUSES) }).parse(data)
}

export async function getExecution(id: string, afterSeq = 0): Promise<ExecutionSnapshot> {
  const data = await api.get<unknown>(`/executions/${id}?afterSeq=${afterSeq}`)
  return executionSnapshotSchema.parse(data)
}

export async function cancelExecution(id: string): Promise<{ id: string; status: ExecutionStatus; alreadyFinished: boolean }> {
  const data = await api.post<unknown>(`/executions/${id}/cancel`)
  return z
    .object({
      id: z.string().uuid(),
      status: z.enum(EXECUTION_STATUSES),
      alreadyFinished: z.boolean(),
    })
    .parse(data)
}
