/**
 * 执行注册表：路由 ExecutionRequest 到正确的 Backend。
 *
 * 用法：
 * ```ts
 * const result = await execute({ mode: 'test', testPaths: ['src/a.test.ts'], files: vfs, languageId: 'typescript' })
 * ```
 */

import type { ExecutionRequest, ExecutionResult } from './types'
import type { ExecutionBackend } from './ExecutionBackend'
import { getProfile } from './LanguageProfile'

const backends = new Map<string, ExecutionBackend>()

export function registerBackend(backend: ExecutionBackend): void {
  backends.set(backend.backendId, backend)
}

export function getBackend(backendId: string): ExecutionBackend | undefined {
  return backends.get(backendId)
}

export class UnsupportedExecutionError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'UnsupportedExecutionError'
  }
}

/** 选择能处理该请求的后端（优先级按注册顺序）。 */
export function selectBackend(request: ExecutionRequest): ExecutionBackend {
  const profile = getProfile(request.languageId)
  if (!profile) {
    throw new UnsupportedExecutionError(`未知语言：${request.languageId}`)
  }
  if (profile.supportedBackends.length === 0) {
    throw new UnsupportedExecutionError(
      `语言 "${profile.displayName}" 当前没有可用的执行后端（规划中，尚未实现——不伪造运行能力）`,
    )
  }
  for (const backend of backends.values()) {
    if (backend.canHandle(request, profile)) {
      return backend
    }
  }
  throw new UnsupportedExecutionError(
    `没有后端能处理 ${request.languageId} 的 ${request.mode} 请求`,
  )
}

/** 统一执行入口：选后端 → execute。 */
export async function execute(request: ExecutionRequest): Promise<ExecutionResult> {
  const backend = selectBackend(request)
  await backend.prepare?.()
  return backend.execute(request)
}
