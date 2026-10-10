/**
 * 调试会话 API（P4.5a）。
 * POST /debug-sessions 创建；GET /{id} 快照轮询；POST /{id}/commands 结构化
 * 指令（白名单）；GET /{id}/variables 懒加载；DELETE 停止。
 */

import { api } from './client'
import { z } from 'zod'

export const DEBUG_STATUSES = ['creating', 'building', 'configuring', 'running', 'paused', 'terminated'] as const
export type DebugStatus = (typeof DEBUG_STATUSES)[number]

export const variableSchema = z.object({
  name: z.string(),
  value: z.string().default(''),
  type: z.string().nullable().default(null),
  evaluateName: z.string().nullable().default(null),
  variablesReference: z.number().int().default(0),
})

export const scopeSchema = z.object({
  name: z.string(),
  variablesReference: z.number().int(),
  expensive: z.boolean().default(false),
  variables: z.array(variableSchema).default([]),
})

export const stackFrameSchema = z.object({
  id: z.number().int(),
  name: z.string(),
  file: z.string().nullable().default(null),
  line: z.number().int().nullable().default(null),
  column: z.number().int().nullable().default(null),
})

export const threadSchema = z.object({
  id: z.number().int(),
  name: z.string(),
  isPrimary: z.boolean().default(false),
})

export const locationSchema = z.object({
  file: z.string().nullable().default(null),
  line: z.number().int().nullable().default(null),
  column: z.number().int().nullable().default(null),
  frameName: z.string().nullable().default(null),
})

export const debugBreakpointSchema = z.object({
  path: z.string(),
  line: z.number().int(),
  verified: z.boolean(),
  message: z.string().nullable().default(null),
})

export const diagnosticSchema = z.object({
  severity: z.enum(['error', 'warning', 'info']).default('error'),
  message: z.string(),
  file: z.string().nullable().default(null),
  line: z.number().int().nullable().default(null),
  column: z.number().int().nullable().default(null),
  source: z.string().default('build'),
})

/** 指针关系图：全部来自真实 evaluate 地址匹配（D38）；未解析/空指针如实标注。 */
export const pointerGraphSchema = z.object({
  addresses: z.record(z.string(), z.string().nullable()),
  verifiedEdges: z.array(z.object({
    from: z.string(), to: z.string(), address: z.string(),
  })).default([]),
  unresolvedPointers: z.array(z.object({ name: z.string(), value: z.string() })).default([]),
  nullPointers: z.array(z.object({ name: z.string(), value: z.string() })).default([]),
  evalLimitReached: z.boolean().default(false),
})

export const debugSnapshotSchema = z.object({
  id: z.string().uuid(),
  language: z.string(),
  status: z.enum(DEBUG_STATUSES),
  endReason: z.string().nullable().default(null),
  entryPoint: z.string(),
  projectId: z.string().uuid().nullable().default(null),
  codeFingerprint: z.string().nullable().default(null),
  debuggerProfile: z.string().nullable().default(null),
  location: locationSchema.nullable().default(null),
  stopReason: z.string().nullable().default(null),
  pauseSeq: z.number().int().default(0),
  threadId: z.number().int().nullable().default(null),
  pointerGraph: pointerGraphSchema.nullable().default(null),
  threads: z.array(threadSchema).default([]),
  stackFrames: z.array(stackFrameSchema).default([]),
  scopes: z.array(scopeSchema).default([]),
  breakpoints: z.array(debugBreakpointSchema).default([]),
  buildDiagnostics: z.array(diagnosticSchema).default([]),
  buildStdout: z.string().default(''),
  error: z.string().nullable().default(null),
  dapLog: z.array(z.record(z.string(), z.unknown())).default([]),
  sandbox: z.object({
    engine: z.string().nullable().default(null),
    image: z.string().nullable().default(null),
  }).default({ engine: null, image: null }),
  createdAt: z.string(),
  startedAt: z.string().nullable().default(null),
  pausedAt: z.string().nullable().default(null),
  finishedAt: z.string().nullable().default(null),
})

export type DebugSnapshot = z.infer<typeof debugSnapshotSchema>
export type DebugVariable = z.infer<typeof variableSchema>
export type DebugScope = z.infer<typeof scopeSchema>
export type DebugStackFrame = z.infer<typeof stackFrameSchema>

export interface DebugBreakpointInput {
  path: string
  lines: number[]
}

export interface StartDebugInput {
  entryPoint: string
  files: Record<string, string>
  breakpoints: DebugBreakpointInput[]
  stopOnEntry?: boolean
  codeFingerprint?: string
  projectId?: string
}

export const DEBUG_COMMANDS = ['continue', 'pause', 'next', 'stepIn', 'stepOut', 'stop', 'setBreakpoints'] as const
export type DebugCommand = (typeof DEBUG_COMMANDS)[number]

export async function startDebugSession(input: StartDebugInput): Promise<{ id: string; status: DebugStatus }> {
  const data = await api.post<unknown>('/debug-sessions', input)
  return z.object({ id: z.string().uuid(), status: z.enum(DEBUG_STATUSES) }).parse(data)
}

export async function getDebugSnapshot(id: string): Promise<DebugSnapshot> {
  const data = await api.get<unknown>(`/debug-sessions/${id}`)
  return debugSnapshotSchema.parse(data)
}

export async function sendDebugCommand(
  id: string,
  command: DebugCommand,
  extra: { threadId?: number; breakpoints?: DebugBreakpointInput[] } = {},
): Promise<DebugSnapshot> {
  const data = await api.post<unknown>(`/debug-sessions/${id}/commands`, { command, ...extra })
  return debugSnapshotSchema.parse(data)
}

export async function expandDebugVariables(id: string, variablesReference: number): Promise<{ variables: DebugVariable[] }> {
  const data = await api.get<unknown>(`/debug-sessions/${id}/variables?variablesReference=${variablesReference}`)
  return z.object({ variables: z.array(variableSchema) }).parse(data)
}

export async function stopDebugSession(id: string): Promise<DebugSnapshot> {
  const data = await api.delete<unknown>(`/debug-sessions/${id}`)
  return debugSnapshotSchema.parse(data)
}

/** 按栈帧取作用域变量（白名单端点；返回 pauseSeq——旧代次缓存不得复用）。 */
export async function getFrameVariables(
  id: string,
  frameId: number,
): Promise<FrameVariables> {
  const data = await api.get<unknown>(`/debug-sessions/${id}/frames/${frameId}/variables`)
  return frameVariablesSchema.parse(data)
}

export const frameVariablesSchema = z.object({
  frameId: z.number().int(),
  pauseSeq: z.number().int(),
  scopes: z.array(scopeSchema).default([]),
  pointerGraph: pointerGraphSchema.nullable().default(null),
})

export type FrameVariables = z.infer<typeof frameVariablesSchema>
export type PointerGraph = z.infer<typeof pointerGraphSchema>
