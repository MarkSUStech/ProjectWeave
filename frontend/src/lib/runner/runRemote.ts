/**
 * 远程执行粘合到终端面板（P4.2b，Python）：
 * 状态行（排队/沙箱/运行）、增量输出流式打印、可取消、结果摘要、trace 绑定。
 * 运行使用编辑器草稿 + 项目文件（VFS），无需先保存。
 */

import { useRunStore } from '../../stores/runStore'
import { fingerprint } from '../fingerprint'
import {
  cancelActiveRemoteExecution,
  executeRemoteWithStream,
  remoteExecutionErrorMessage,
  remoteBackendIdForLanguage,
} from '../execution/backends/remoteShared'
import { detectLanguage, getProfile, isTestFile } from '../execution/LanguageProfile'
import { isRunnablePath, isTestPath } from './runFile'
import type { VirtualFS } from '../execution/types'
import type { RunStatus } from '../../types/runner'

/** 语言是否具备远程执行后端（按 Profile 声明，自动覆盖未来语言）。 */
export function isRemoteExecutable(path: string): boolean {
  const lang = detectLanguage(path)
  if (lang === null || lang === 'typescript') return false
  const profile = getProfile(lang)
  return (profile?.supportedBackends.length ?? 0) > 0
}

/** 文件是否可执行（浏览器 js/ts 或远程语言）。 */
export function canRunPath(path: string): boolean {
  return isRunnablePath(path) || isRemoteExecutable(path)
}

/** 是否为测试文件（TS 约定或远程语言的测试命名，如 test_*.py / *_test.cpp）。 */
export function isAnyTestPath(path: string): boolean {
  if (isTestPath(path)) return true
  const lang = detectLanguage(path)
  return lang !== null && isTestFile(path, lang)
}

export interface RemoteRunOutcome {
  status: RunStatus
  traceId: string | null
  executionId: string | null
  exitCode: number | null
  ok: boolean
}

/** 运行（run 模式）：入口 = 当前文件。 */
export async function runRemoteInTerminal(
  path: string,
  files: VirtualFS,
  options: { timeoutMs?: number; projectId?: string } = {},
): Promise<RemoteRunOutcome> {
  return runRemoteMode({
    mode: 'run',
    entryPoint: path,
    testPaths: [],
    files,
    ...options,
  })
}

/** 测试（test 模式）：运行给定测试文件。 */
export async function runRemoteTestsInTerminal(
  testPaths: string[],
  files: VirtualFS,
  options: { timeoutMs?: number; projectId?: string } = {},
): Promise<RemoteRunOutcome> {
  return runRemoteMode({
    mode: 'test',
    entryPoint: undefined,
    testPaths,
    files,
    ...options,
  })
}

async function runRemoteMode(args: {
  mode: 'run' | 'test'
  entryPoint?: string
  testPaths: string[]
  files: VirtualFS
  timeoutMs?: number
  projectId?: string
}): Promise<RemoteRunOutcome> {
  const store = useRunStore.getState()
  if (store.running) {
    return { status: 'error', traceId: null, executionId: null, exitCode: null, ok: false }
  }

  // 语言由入口/首个测试文件推断（传输层语言无关，服务端按语言路由 Runner）
  const probePath = args.entryPoint ?? args.testPaths[0] ?? ''
  const languageId = detectLanguage(probePath)
  if (languageId === null || languageId === 'typescript' || !remoteBackendIdForLanguage(languageId)) {
    return { status: 'error', traceId: null, executionId: null, exitCode: null, ok: false }
  }
  const backendId = remoteBackendIdForLanguage(languageId)!
  const engineLabel = languageId === 'cpp' ? 'C++ · Clang 15 / C++20' : 'Python 3.12'
  const target = args.mode === 'run' ? args.entryPoint : `${args.testPaths.length} 个测试文件`
  store.setActiveTab('terminal')
  store.appendEntry('system', `▶ ${args.mode === 'run' ? '运行' : '测试'} ${target}（远程沙箱 · ${engineLabel}）`)

  const traceId = crypto.randomUUID()
  const content = args.entryPoint ? (args.files.get(args.entryPoint) ?? '') : ''
  const contentFingerprint = args.entryPoint
    ? await fingerprint(args.entryPoint, content)
    : await Promise.all(
        [...args.files.keys()].sort().map(async (p) => fingerprint(p, args.files.get(p) ?? '')),
      ).then((parts) => parts.join('\n'))
  const stdin = useRunStore.getState().stdin

  useRunStore.getState().setTrace({
    traceId,
    fingerprint: contentFingerprint,
    runPath: args.entryPoint ?? null,
    at: new Date().toISOString(),
    backend: backendId,
    executionId: null,
  })
  useRunStore.getState().setRunning(true)

  let printedLines = 0
  try {
    const { extras, ...result } = await executeRemoteWithStream(
      {
        mode: args.mode,
        entryPoint: args.entryPoint,
        testPaths: args.testPaths,
        files: args.files,
        languageId,
        timeoutMs: args.timeoutMs,
        codeFingerprint: contentFingerprint,
        stdin,
        projectId: args.projectId,
      },
      (channel, text) => {
        // 流式输出：保持原始分块顺序直接进终端
        printedLines += 1
        useRunStore.getState().appendEntry(channel === 'stderr' ? 'error' : 'log', text.replace(/\n$/, ''))
      },
      (executionId) => useRunStore.getState().setActiveExecutionId(executionId),
    )
    useRunStore.getState().setActiveExecutionId(null)
    useRunStore.getState().setTrace({
      traceId,
      fingerprint: contentFingerprint,
      runPath: args.entryPoint ?? null,
      at: new Date().toISOString(),
      backend: backendId,
      executionId: extras.executionId,
    })

    if (extras.status === 'cancelled') {
      useRunStore.getState().appendEntry('system', '■ 已取消（沙箱已销毁）')
      return { status: 'error', traceId, executionId: extras.executionId, exitCode: null, ok: false }
    }
    if (extras.timedOut) {
      useRunStore.getState().appendEntry('error', `✘ 执行超时（${extras.runTimeMs}ms），沙箱已终止`)
      return { status: 'timeout', traceId, executionId: extras.executionId, exitCode: null, ok: false }
    }
    // 构建诊断（编译/链接错误 → 文件:行:列）
    for (const diag of result.buildDiagnostics) {
      const where = diag.file
        ? `${diag.file}${diag.line ? `:${diag.line}` : ''}${diag.column ? `:${diag.column}` : ''}`
        : ''
      useRunStore.getState().appendEntry('error', `[构建] ${where ? `${where} ` : ''}${diag.message}`)
    }
    // 运行诊断（traceback / 崩溃信号 / 取消）
    for (const diag of result.runtimeDiagnostics) {
      const where = diag.file ? `${diag.file}${diag.line ? `:${diag.line}` : ''}` : ''
      useRunStore.getState().appendEntry('error', `${where ? `[${where}] ` : ''}${diag.message}`)
    }
    if (result.ok) {
      useRunStore.getState().appendEntry('system', `✔ 完成（${extras.runTimeMs}ms）`)
    } else if (printedLines === 0 && result.output.length === 0) {
      useRunStore.getState().appendEntry('error', '✘ 执行失败（无输出）')
    } else {
      useRunStore.getState().appendEntry('system', `✘ 退出码 ${extras.exitCode}（${extras.runTimeMs}ms）`)
    }
    return {
      status: result.ok ? 'ok' : 'error',
      traceId,
      executionId: extras.executionId,
      exitCode: extras.exitCode,
      ok: result.ok,
    }
  } catch (err) {
    // 明确呈现失败原因（沙箱不可用/网络/校验），不伪装成功
    useRunStore.getState().appendEntry('error', `✘ ${remoteExecutionErrorMessage(err)}`)
    return { status: 'error', traceId, executionId: null, exitCode: null, ok: false }
  } finally {
    useRunStore.getState().setRunning(false)
    useRunStore.getState().setActiveExecutionId(null)
  }
}

/** 终端「停止」按钮：取消当前远程执行。 */
export async function stopRemoteExecution(): Promise<void> {
  const store = useRunStore.getState()
  if (!store.activeExecutionId) {
    // 轮询尚未拿到会话 id 时也允许尝试（后端模块跟踪活动会话）
    const id = await cancelActiveRemoteExecution()
    if (id) store.appendEntry('system', '■ 正在取消…')
    return
  }
  store.appendEntry('system', '■ 正在取消…')
  await cancelActiveRemoteExecution()
}
