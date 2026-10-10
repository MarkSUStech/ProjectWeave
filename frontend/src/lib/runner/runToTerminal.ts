/**
 * 把一次“运行”粘合到终端面板：状态行、流式输出、结果摘要。
 * 运行使用编辑器当前内容（草稿），不需要先保存。
 */

import { useRunStore } from '../../stores/runStore'
import { prepareScript } from './runFile'
import { runJavaScript } from './runJavaScript'
import type { RunStatus } from '../../types/runner'

export interface RunFileInTerminalOptions {
  timeoutMs?: number
}

export async function runFileInTerminal(
  path: string,
  content: string,
  options: RunFileInTerminalOptions = {},
): Promise<RunStatus> {
  const store = useRunStore.getState()
  if (store.running) return 'error'

  store.setActiveTab('terminal')
  store.appendEntry('system', `▶ 运行 ${path}（浏览器 Worker 沙箱，${options.timeoutMs ?? 5000}ms 超时）`)

  const prepared = await prepareScript(path, content)
  if (prepared.status === 'unsupported') {
    store.appendEntry('error', `✘ ${prepared.reason}`)
    return 'unsupported'
  }
  if (prepared.transpiled) {
    store.appendEntry('system', 'TypeScript 已单文件转译执行（不做类型检查）')
  }

  useRunStore.getState().setRunning(true)
  const result = await runJavaScript(prepared.code, {
    timeoutMs: options.timeoutMs,
    onEntry: (level, text) => useRunStore.getState().appendEntry(level, text),
  })
  useRunStore.getState().setRunning(false)

  if (result.ok) {
    useRunStore.getState().appendEntry('system', `✔ 完成（${result.durationMs}ms）`)
    return 'ok'
  }
  useRunStore.getState().appendEntry(
    'error',
    `✘ ${result.error ? `${result.error}\n` : ''}（耗时 ${result.durationMs}ms）`,
  )
  return result.error?.includes('超时') ? 'timeout' : 'error'
}
