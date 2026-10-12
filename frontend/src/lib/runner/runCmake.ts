/**
 * CMake 项目操作粘合到终端（P8.1）：discover / build / run / test。
 *
 * 全部走真实后端执行会话（受限 Docker 沙箱内 CMake Configure → File API
 * 目标发现 → 构建/运行/CTest），结果与诊断如实进终端；目标只能来自
 * discover 返回的真实列表。
 */

import { useRunStore } from '../../stores/runStore'
import {
  executeRemoteWithStream,
  remoteExecutionErrorMessage,
} from '../execution/backends/remoteShared'
import type { VirtualFS } from '../execution/types'
import type { CmakeTarget } from '../../api/executions'

export interface CmakeTestEntry {
  path: string
  status: 'passed' | 'failed' | 'error' | 'skipped'
  error?: string
  cases: Array<{ name: string; status: 'passed' | 'failed' | 'error' | 'skipped'; error?: string; durationMs: number }>
}

export interface CmakeOutcome {
  ok: boolean
  exitCode: number | null
  executionId: string | null
  /** discover：真实发现的目标列表（失败为空）。 */
  targets: CmakeTarget[]
  /** test：真实发现的测试名。 */
  discoveredTests: string[]
  /** test：逐 CTest 测试结果（与测试面板 TestFileResult 同形）。 */
  testResults: CmakeTestEntry[]
  cmakeVersion: string | null
  generator: string | null
}

const CMAKE_TIMEOUT_MS = 120_000

const EMPTY: CmakeOutcome = {
  ok: false, exitCode: null, executionId: null,
  targets: [], discoveredTests: [], testResults: [], cmakeVersion: null, generator: null,
}

async function runCmakeSession(args: {
  operation: string
  mode: 'run' | 'test'
  files: VirtualFS
  projectId?: string
  cmakeAction?: 'discover' | 'build' | 'run'
  targetName?: string
  selectedTests?: string[]
  summaryLine: string
}): Promise<CmakeOutcome> {
  const store = useRunStore.getState()
  if (store.running) return { ...EMPTY }
  store.setActiveTab('terminal')
  store.appendEntry('system', args.summaryLine)
  useRunStore.getState().setRunning(true)

  try {
    const { extras, ...result } = await executeRemoteWithStream(
      {
        mode: args.mode,
        entryPoint: undefined,
        testPaths: [],
        files: args.files,
        languageId: 'cpp',
        timeoutMs: CMAKE_TIMEOUT_MS,
        buildSystem: 'cmake',
        cmakeAction: args.cmakeAction,
        targetName: args.targetName,
        selectedTests: args.selectedTests,
        projectId: args.projectId,
      },
      (channel, text) => {
        useRunStore.getState().appendEntry(channel === 'stderr' ? 'error' : 'log', text.replace(/\n$/, ''))
      },
      (executionId) => useRunStore.getState().setActiveExecutionId(executionId),
    )
    useRunStore.getState().setActiveExecutionId(null)

    if (extras.status === 'cancelled') {
      useRunStore.getState().appendEntry('system', '■ 已取消（沙箱已销毁）')
      return { ...EMPTY, executionId: extras.executionId }
    }
    if (extras.timedOut) {
      useRunStore.getState().appendEntry('error', `✘ 执行超时（${extras.runTimeMs}ms），沙箱已终止`)
      return { ...EMPTY, executionId: extras.executionId }
    }
    for (const diag of result.buildDiagnostics) {
      const where = diag.file
        ? `${diag.file}${diag.line ? `:${diag.line}` : ''}${diag.column ? `:${diag.column}` : ''}`
        : ''
      useRunStore.getState().appendEntry('error', `[构建] ${where ? `${where} ` : ''}${diag.message}`)
    }
    for (const diag of result.runtimeDiagnostics) {
      const where = diag.file ? `${diag.file}${diag.line ? `:${diag.line}` : ''}` : ''
      useRunStore.getState().appendEntry('error', `${where ? `[${where}] ` : ''}${diag.message}`)
    }
    if (result.testResults) {
      for (const file of result.testResults) {
        for (const c of file.cases) {
          if (c.status !== 'passed') {
            useRunStore.getState().appendEntry('error', `[CTest] ${c.name}：${c.status}${c.error ? ` — ${c.error}` : ''}`)
          }
        }
      }
    }
    if (result.ok) {
      useRunStore.getState().appendEntry('system', `✔ 完成（${extras.runTimeMs}ms）`)
    } else {
      useRunStore.getState().appendEntry('system', `✘ 退出码 ${extras.exitCode}（${extras.runTimeMs}ms）`)
    }
    return {
      ok: result.ok,
      exitCode: extras.exitCode,
      executionId: extras.executionId,
      targets: extras.cmake?.targets ?? [],
      discoveredTests: extras.cmake?.discoveredTests ?? [],
      testResults: (result.testResults ?? []).map((file) => ({
        path: file.path,
        status: file.status,
        error: file.error,
        cases: file.cases.map((c) => ({
          name: c.name, status: c.status, error: c.error, durationMs: c.durationMs,
        })),
      })),
      cmakeVersion: extras.cmake?.cmakeVersion ?? null,
      generator: extras.cmake?.generator ?? null,
    }
  } catch (err) {
    useRunStore.getState().appendEntry('error', `✘ ${remoteExecutionErrorMessage(err)}`)
    return { ...EMPTY }
  } finally {
    useRunStore.getState().setRunning(false)
    useRunStore.getState().setActiveExecutionId(null)
  }
}

/** Configure + 目标发现（File API），返回真实目标列表。 */
export function cmakeDiscoverInTerminal(files: VirtualFS, projectId?: string): Promise<CmakeOutcome> {
  return runCmakeSession({
    operation: 'discover', mode: 'run', cmakeAction: 'discover',
    files, projectId,
    summaryLine: '▶ CMake Configure · 目标发现（File API · 远程沙箱 CMake/Ninja）',
  })
}

/** 构建指定目标（不运行）。 */
export function cmakeBuildInTerminal(
  files: VirtualFS, targetName: string, projectId?: string,
): Promise<CmakeOutcome> {
  return runCmakeSession({
    operation: 'build', mode: 'run', cmakeAction: 'build', targetName,
    files, projectId,
    summaryLine: `▶ Building target: ${targetName} [CMake / Debug]`,
  })
}

/** 构建并运行指定目标（产物路径来自 File API）。 */
export function cmakeRunInTerminal(
  files: VirtualFS, targetName: string, projectId?: string,
): Promise<CmakeOutcome> {
  return runCmakeSession({
    operation: 'run', mode: 'run', cmakeAction: 'run', targetName,
    files, projectId,
    summaryLine: `▶ Building target: ${targetName} [CMake / Debug]`,
  })
}

/** CTest：运行全部（或选定）测试。 */
export function cmakeTestInTerminal(
  files: VirtualFS, projectId?: string, selectedTests?: string[],
): Promise<CmakeOutcome> {
  return runCmakeSession({
    operation: 'test', mode: 'test', selectedTests,
    files, projectId,
    summaryLine: `▶ CTest 运行测试${selectedTests?.length ? `（已选 ${selectedTests.length} 个）` : '（全部）'} [CMake / Debug]`,
  })
}
