/**
 * 远程执行共享传输层（P4.2c 抽自 remotePython）：
 * 创建会话 → 轮询（增量事件流式回传）→ 终态映射为语言无关 ExecutionResult。
 *
 * 传输层与语言无关（服务端按 language 路由 Runner）——Python/C++/未来
 * 语言只差 backendId 与能力声明，复用同一实现。
 */

import type {
  ConsoleOutput,
  Diagnostic,
  ExecutionRequest,
  ExecutionResult,
  TestFileOutcome,
} from '../types'
import type { ExecutionBackend } from '../ExecutionBackend'

import {
  cancelExecution as apiCancelExecution,
  createExecution,
  getExecution,
  TERMINAL_STATUSES,
  type ExecutionSnapshot,
} from '../../../api/executions'
import { ApiError } from '../../../api/client'

const POLL_INTERVAL_MS = 400
const POLL_TIMEOUT_MS = 180_000

/** 语言 → 远程后端 id（trace 溯源用；与各后端文件的 backendId 一致）。 */
export const REMOTE_BACKEND_IDS = {
  python: 'remote-pytest',
  cpp: 'remote-cpp',
} as const

export function remoteBackendIdForLanguage(languageId: string): string | null {
  const id = (REMOTE_BACKEND_IDS as Record<string, string>)[languageId]
  return id ?? null
}

/** 当前活动执行会话（取消按钮用；单活动执行假设与 IDE 交互一致）。 */
let activeExecutionId: string | null = null

export function getActiveRemoteExecutionId(): string | null {
  return activeExecutionId
}

export async function cancelActiveRemoteExecution(): Promise<string | null> {
  const id = activeExecutionId
  if (!id) return null
  try {
    await apiCancelExecution(id)
    return id
  } catch {
    // 取消失败（网络/已结束）时不清除引用，由轮询终态收敛
    return null
  }
}

function channelToLevel(channel: string): ConsoleOutput['level'] {
  return channel === 'stderr' ? 'error' : 'log'
}

function toDiagnostic(d: ExecutionSnapshot['diagnostics'][number], source: Diagnostic['source']): Diagnostic {
  return {
    severity: d.severity,
    message: d.message,
    file: d.file ?? undefined,
    line: d.line ?? undefined,
    column: d.column ?? undefined,
    source,
  }
}

function snapshotToResult(snap: ExecutionSnapshot, request: ExecutionRequest): ExecutionResult {
  const output: ConsoleOutput[] = []
  for (const event of snap.events) {
    output.push({ level: channelToLevel(event.channel), text: event.text })
  }
  if (output.length === 0) {
    // 事件流为空（如异常路径）时退回完整输出
    if (snap.stdout) output.push({ level: 'log', text: snap.stdout })
    if (snap.stderr) output.push({ level: 'error', text: snap.stderr })
  }

  // 诊断按阶段分类：build（编译/链接）| runtime（运行/崩溃/超时）| test（断言）
  const buildDiagnostics = snap.diagnostics.filter((d) => d.source === 'build').map((d) => toDiagnostic(d, 'build'))
  const runtimeDiagnostics = snap.diagnostics.filter((d) => d.source === 'runtime').map((d) => toDiagnostic(d, 'runtime'))
  const testDiagnostics = snap.diagnostics.filter((d) => d.source === 'test').map((d) => toDiagnostic(d, 'test'))

  if (snap.error) {
    runtimeDiagnostics.push({ severity: 'error', message: snap.error, source: 'runtime' })
  }
  if (snap.status === 'timed-out') {
    runtimeDiagnostics.push({
      severity: 'error',
      message: `执行超时（${snap.timeoutMs}ms），沙箱已终止`,
      source: 'runtime',
    })
  }
  if (snap.status === 'cancelled') {
    runtimeDiagnostics.push({ severity: 'warning', message: '执行已取消', source: 'runtime' })
  }

  const testResults: TestFileOutcome[] | undefined = snap.testResults
    ? snap.testResults.map((file) => ({
        path: file.path,
        status: file.status,
        error: file.error ?? undefined,
        cases: file.cases.map((c) => ({
          name: c.name,
          // skipped（未执行/被过滤）如实透传，不得伪装成失败或通过
          status: c.status === 'passed' ? ('passed' as const)
            : c.status === 'skipped' ? ('skipped' as const) : ('failed' as const),
          error: c.error ?? undefined,
          durationMs: c.durationMs,
        })),
      }))
    : undefined

  let ok: boolean
  if (snap.status !== 'completed') {
    ok = false
  } else if (request.mode === 'run') {
    ok = snap.exitCode === 0 && !snap.timedOut
  } else {
    ok =
      testResults !== undefined &&
      testResults.length > 0 &&
      testResults.every((t) => t.status === 'passed')
  }

  return {
    ok,
    mode: request.mode,
    buildDiagnostics,
    runtimeDiagnostics: [...runtimeDiagnostics, ...testDiagnostics],
    output,
    testResults,
    modules: [...request.files.keys()],
    buildTimeMs: 0,
    runTimeMs: snap.runTimeMs,
    codeFingerprint: request.codeFingerprint,
  }
}

export interface RemoteExecutionExtras {
  /** 执行会话 id（验收溯源用）。 */
  executionId: string
  /** 退出码与终态。 */
  status: ExecutionSnapshot['status']
  exitCode: number | null
  timedOut: boolean
  cancelled: boolean
  runTimeMs: number
  /** P8.1：CMake profile 结构化结果（目标列表/产物路径；direct 为 null）。 */
  cmake: ExecutionSnapshot['cmake']
}

/** 带流式回调的执行（终端实时输出）。P8.1 起透传 CMake profile 字段。 */
export async function executeRemoteWithStream(
  request: ExecutionRequest & {
    stdin?: string
    projectId?: string
    buildSystem?: 'direct' | 'cmake'
    cmakeAction?: 'discover' | 'build' | 'run'
    targetName?: string
    selectedTests?: string[]
  },
  onEvent?: (channel: 'stdout' | 'stderr' | 'system', text: string) => void,
  onCreated?: (executionId: string) => void,
): Promise<ExecutionResult & { extras: RemoteExecutionExtras }> {
  const created = await createExecution({
    language: request.languageId,
    mode: request.mode,
    entryPoint: request.entryPoint,
    testPaths: request.testPaths,
    files: Object.fromEntries(request.files),
    stdin: request.stdin,
    timeoutMs: request.timeoutMs,
    codeFingerprint: request.codeFingerprint,
    projectId: request.projectId,
    buildSystem: request.buildSystem,
    cmakeAction: request.cmakeAction,
    targetName: request.targetName,
    selectedTests: request.selectedTests,
  })
  activeExecutionId = created.id
  onCreated?.(created.id)

  let afterSeq = 0
  const deadline = Date.now() + POLL_TIMEOUT_MS
  for (;;) {
    const snap = await getExecution(created.id, afterSeq)
    for (const event of snap.events) {
      onEvent?.(event.channel, event.text)
      afterSeq = Math.max(afterSeq, event.seq)
    }
    if (TERMINAL_STATUSES.has(snap.status)) {
      activeExecutionId = null
      const result = snapshotToResult(snap, request)
      return {
        ...result,
        extras: {
          executionId: snap.id,
          status: snap.status,
          exitCode: snap.exitCode,
          timedOut: snap.timedOut,
          cancelled: snap.cancelled,
          runTimeMs: snap.runTimeMs,
          cmake: snap.cmake,
        },
      }
    }
    if (Date.now() > deadline) {
      activeExecutionId = null
      await apiCancelExecution(created.id).catch(() => undefined)
      throw new Error('远程执行轮询超时（已请求取消）')
    }
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS))
  }
}

/**
 * 远程后端工厂：传输/取消/映射全部共享，语言只声明 backendId 与能力。
 * 信任级固定 practice（服务端执行 ≠ 正式认证，D32）。
 */
export function createRemoteBackend(options: {
  backendId: string
  languages: string[]
}): ExecutionBackend {
  return {
    backendId: options.backendId,
    capabilities: {
      languages: options.languages,
      multiFile: true,
      testRunner: true,
      inBrowser: false,
      maxTrustLevel: 'practice',
    },
    canHandle(request, profile) {
      return (
        options.languages.includes(request.languageId) &&
        profile.supportedBackends.includes(options.backendId)
      )
    },
    async execute(request) {
      const { extras: _extras, ...result } = await executeRemoteWithStream(request)
      return result
    },
  }
}

/** ApiError（如 503 沙箱不可用）转可读消息——调用方捕获后展示。 */
export function remoteExecutionErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 503) return `远程沙箱不可用：${err.message}`
    return `远程执行请求失败：${err.message}`
  }
  if (err instanceof Error) return err.message
  return String(err)
}
