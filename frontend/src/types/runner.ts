/** 浏览器运行器相关类型。 */

export type ConsoleLevel = 'log' | 'info' | 'warn' | 'error'

export interface ConsoleMessage {
  type: 'console'
  level: ConsoleLevel
  text: string
}

/** observe(name, value) 上报的变量状态变化（真实执行采集，§9.4 图-代码闭环的教学通道）。 */
export interface ObservedMessage {
  type: 'observed'
  name: string
  text: string
}

/** 单个测试用例的执行结果（Worker → 主线程，流式）。 */
export interface TestResultMessage {
  type: 'test-result'
  name: string
  status: 'passed' | 'failed'
  error?: string
  durationMs: number
}

/** 一个测试文件执行完的汇总（Worker → 主线程，随后紧跟 done）。 */
export interface TestSummaryMessage {
  type: 'test-summary'
  total: number
  passed: number
  failed: number
}

export type WorkerMessage =
  | ConsoleMessage
  | ObservedMessage
  | TestResultMessage
  | TestSummaryMessage
  | { type: 'done'; result: string }
  | { type: 'error'; message: string }

export interface RunResult {
  ok: boolean
  /** 从开始执行到 done/error/超时的毫秒数。 */
  durationMs: number
  /** ok=false 时的错误描述（异常栈 / 超时 / 加载失败）。 */
  error?: string
}

export type RunStatus = 'ok' | 'error' | 'unsupported' | 'timeout'

/** 测试面板的领域模型（主线程聚合后）。 */
export interface TestCaseResult {
  name: string
  status: 'passed' | 'failed' | 'skipped'
  error?: string
  durationMs: number
}

export interface TestFileResult {
  path: string
  status: 'passed' | 'failed' | 'error' | 'skipped'
  /** status=error（加载/执行失败）时的原因。 */
  error?: string
  cases: TestCaseResult[]
}

/** 终端面板条目（system 为运行器自身的状态行）。 */
export interface TerminalEntry {
  id: number
  kind: 'system' | ConsoleLevel
  text: string
  /** ISO 时间，用于渲染时间戳。 */
  at: string
}

/** 变量状态观察记录（observe 上报，可视化组件数据源）。 */
export interface Observation {
  id: number
  name: string
  value: string
  at: string
}
