/**
 * 在隔离 Web Worker 中执行 JS 代码，控制台输出与测试事件实时流回主线程。
 *
 * - Worker 以 Blob URL + module 模式创建，无法访问 DOM 与应用状态；
 * - 超时（默认 5s）后强制 terminate，防止死循环占用；
 * - Worker 脚本加载失败（如语法错误）通过 error 事件上报；
 * - 无论如何结束都会 terminate。
 * - 测试模式（buildTestSource）的结束协议：test-summary 之后紧跟 done，
 *   因此主线程结束条件与普通运行一致（done/error）。
 */

import { buildTestSource, buildWorkerSource } from './workerSource'
import type { ConsoleLevel, RunResult, TestCaseResult, TestSummaryMessage, WorkerMessage } from '../../types/runner'

export const DEFAULT_TIMEOUT_MS = 5000

export type WorkerFactory = (source: string) => Worker

export const defaultCreateWorker: WorkerFactory = (source) => {
  // 注意：模块 Worker 的脚本加载是异步的，立即 revokeObjectURL 有竞态风险；
  // 每个 blob 只有脚本文本大小（KB 级），教学场景下不主动回收，页面卸载时统一释放。
  const url = URL.createObjectURL(new Blob([source], { type: 'text/javascript' }))
  return new Worker(url, { type: 'module' })
}

export interface RunJavaScriptOptions {
  timeoutMs?: number
  /** 每条 console 输出的回调（流式）。 */
  onEntry?: (level: ConsoleLevel, text: string) => void
  /** 所有 Worker 消息的回调（含 test-result / test-summary），供测试模式使用。 */
  onMessage?: (message: WorkerMessage) => void
  /** 测试注入用。 */
  createWorker?: WorkerFactory
}

export function runJavaScript(
  code: string,
  options: RunJavaScriptOptions = {},
): Promise<RunResult> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, onEntry, onMessage, createWorker = defaultCreateWorker } = options
  let worker: Worker
  try {
    worker = createWorker(buildWorkerSource(code))
  } catch (err) {
    return Promise.resolve({ ok: false, durationMs: 0, error: `无法创建运行环境：${String(err)}` })
  }
  return runWorker(worker, { timeoutMs, onEntry, onMessage })
}

function runWorker(
  worker: Worker,
  {
    timeoutMs,
    onEntry,
    onMessage,
  }: { timeoutMs: number; onEntry?: RunJavaScriptOptions['onEntry']; onMessage?: RunJavaScriptOptions['onMessage'] },
): Promise<RunResult> {
  const startedAt = Date.now()

  return new Promise<RunResult>((resolve) => {
    let settled = false
    const finish = (result: RunResult) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      worker.terminate()
      resolve(result)
    }
    const elapsed = () => Date.now() - startedAt

    const timer = setTimeout(() => {
      finish({ ok: false, durationMs: elapsed(), error: `执行超时（>${timeoutMs}ms），已强制终止。` })
    }, timeoutMs)

    worker.addEventListener('message', (event: MessageEvent) => {
      const data = event.data as WorkerMessage | undefined
      if (!data || typeof data !== 'object') return
      onMessage?.(data)
      if (data.type === 'console') {
        onEntry?.(data.level, data.text)
      } else if (data.type === 'done') {
        finish({ ok: true, durationMs: elapsed() })
      } else if (data.type === 'error') {
        finish({ ok: false, durationMs: elapsed(), error: String(data.message) })
      }
    })

    worker.addEventListener('error', (event: ErrorEvent) => {
      const detail = event.message || '脚本加载失败（通常是语法错误）'
      finish({ ok: false, durationMs: elapsed(), error: detail })
    })
  })
}

export interface TestRunOutcome {
  result: RunResult
  cases: TestCaseResult[]
  summary?: TestSummaryMessage
}

/** 在 Worker 沙箱中执行一个测试文件（buildTestSource 注入测试运行时）。 */
export function runTests(
  code: string,
  options: Omit<RunJavaScriptOptions, 'onMessage'> & {
    onTestCase?: (testCase: TestCaseResult) => void
  } = {},
): Promise<TestRunOutcome> {
  const { onTestCase, ...rest } = options
  const cases: TestCaseResult[] = []
  let summary: TestSummaryMessage | undefined
  let worker: Worker
  try {
    worker = (rest.createWorker ?? defaultCreateWorker)(buildTestSource(code))
  } catch (err) {
    return Promise.resolve({
      result: { ok: false, durationMs: 0, error: `无法创建运行环境：${String(err)}` },
      cases,
      summary,
    })
  }
  const resultPromise = runWorker(worker, {
    timeoutMs: rest.timeoutMs ?? DEFAULT_TIMEOUT_MS,
    onEntry: rest.onEntry,
    onMessage: (message) => {
      if (message.type === 'test-result') {
        const testCase: TestCaseResult = {
          name: message.name,
          status: message.status,
          error: message.error,
          durationMs: message.durationMs,
        }
        cases.push(testCase)
        onTestCase?.(testCase)
      } else if (message.type === 'test-summary') {
        summary = message
      }
    },
  })

  return resultPromise.then((result) => ({ result, cases, summary }))
}
