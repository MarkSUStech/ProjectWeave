/**
 * 把一次“运行”粘合到终端面板：状态行、流式输出、结果摘要。
 * 运行使用编辑器当前内容（草稿），不需要先保存。
 */

import { useRunStore } from '../../stores/runStore'
import { fingerprint } from '../fingerprint'
import { prepareScript } from './runFile'
import { runJavaScript } from './runJavaScript'
import type { RunStatus } from '../../types/runner'

export interface RunFileInTerminalOptions {
  timeoutMs?: number
}

/** 运行并返回 {status, traceId}——traceId 供学习事件与画布关联（§14.3）。 */
export async function runFileInTerminal(
  path: string,
  content: string,
  options: RunFileInTerminalOptions = {},
): Promise<{ status: RunStatus; traceId: string | null }> {
  const store = useRunStore.getState()
  if (store.running) return { status: 'error', traceId: null }

  store.setActiveTab('terminal')
  store.appendEntry('system', `▶ 运行 ${path}（浏览器 Worker 沙箱，${options.timeoutMs ?? 5000}ms 超时）`)

  const prepared = await prepareScript(path, content)
  if (prepared.status === 'unsupported') {
    store.appendEntry('error', `✘ ${prepared.reason}`)
    return { status: 'unsupported', traceId: null }
  }
  if (prepared.transpiled) {
    store.appendEntry('system', 'TypeScript 已单文件转译执行（不做类型检查）')
  }

  // 版本绑定：记录被执行内容（草稿）的指纹；画布据此判定"数据已过期"。
  const traceId = crypto.randomUUID()
  const contentFingerprint = await fingerprint(path, content)
  useRunStore.getState().setTrace({
    traceId,
    fingerprint: contentFingerprint,
    runPath: path,
    at: new Date().toISOString(),
  })

  useRunStore.getState().setRunning(true)
  const result = await runJavaScript(prepared.code, {
    timeoutMs: options.timeoutMs,
    onEntry: (level, text) => useRunStore.getState().appendEntry(level, text),
    onObserved: (name, value) => useRunStore.getState().appendObservation(name, value),
  })
  useRunStore.getState().setRunning(false)

  if (result.ok) {
    useRunStore.getState().appendEntry('system', `✔ 完成（${result.durationMs}ms）`)
    return { status: 'ok', traceId }
  }
  useRunStore.getState().appendEntry(
    'error',
    `✘ ${result.error ? `${result.error}\n` : ''}（耗时 ${result.durationMs}ms）`,
  )
  return {
    status: result.error?.includes('超时') ? 'timeout' : 'error',
    traceId,
  }
}
