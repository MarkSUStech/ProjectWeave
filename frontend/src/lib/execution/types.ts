/**
 * 语言无关的执行契约（P4.2a 前瞻性架构）。
 *
 * 这层是纯类型定义——不含任何具体语言的运行逻辑。
 * TypeScript/Python/C++ 通过 LanguageProfile + ExecutionBackend 组合接入。
 *
 * 设计原则：
 * - ExecutionRequest 描述"做什么"，不含"怎么做"；
 * - Diagnostic 统一构建期与运行期错误报告；
 * - ExecutionResult 携带 traceId/指纹，与学习证据/快照/事件关联；
 * - 信任级始终由调用方（评估端点）决定，执行层不做认证判断。
 */

/** 虚拟文件系统：项目路径 → 文件内容。 */
export type VirtualFS = Map<string, string>

export type ExecutionMode = 'run' | 'test'

export type TrustLevel = 'practice' | 'formal'

export interface ExecutionRequest {
  /** 'run' = 运行入口文件；'test' = 运行测试文件。 */
  mode: ExecutionMode
  /** 入口文件路径（run 模式）或测试文件路径列表（test 模式）。 */
  entryPoint?: string
  testPaths?: string[]
  /** 项目全部文件（含入口/测试/依赖源码）。 */
  files: VirtualFS
  /** 目标语言（由 LanguageProfile 声明支持范围）。 */
  languageId: string
  /** 执行超时（毫秒），默认由 Backend 决定。 */
  timeoutMs?: number
  /** 远程执行的标准输入（随请求一次性提交；浏览器后端忽略）。 */
  stdin?: string
  /** 版本追踪：与运行数据绑定的指纹。 */
  codeFingerprint?: string
}

export type DiagnosticSeverity = 'error' | 'warning' | 'info'

export interface Diagnostic {
  severity: DiagnosticSeverity
  message: string
  file?: string
  line?: number
  column?: number
  /** 错误来源：构建期 / 运行期 / 测试断言。 */
  source: 'build' | 'runtime' | 'test'
}

export interface ConsoleOutput {
  level: 'log' | 'info' | 'warn' | 'error'
  text: string
  /** 相对输出的毫秒偏移（时间线用）。 */
  offsetMs?: number
}

export interface TestCaseOutcome {
  name: string
  status: 'passed' | 'failed' | 'skipped' | 'error'
  error?: string
  durationMs: number
}

export interface TestFileOutcome {
  path: string
  status: 'passed' | 'failed' | 'error' | 'skipped'
  cases: TestCaseOutcome[]
  error?: string
}

export interface ExecutionResult {
  /** 整体是否成功（构建+运行无致命错误）。 */
  ok: boolean
  mode: ExecutionMode
  /** 构建阶段诊断（编译错误、模块解析失败等）。 */
  buildDiagnostics: Diagnostic[]
  /** 运行阶段诊断（运行时异常、超时等）。 */
  runtimeDiagnostics: Diagnostic[]
  /** 控制台输出（流式）。 */
  output: ConsoleOutput[]
  /** 测试结果（仅 test 模式）。 */
  testResults?: TestFileOutcome[]
  /** 参与构建/执行的模块列表。 */
  modules: string[]
  /** 构建耗时（毫秒）。 */
  buildTimeMs: number
  /** 运行耗时（毫秒，不含构建）。 */
  runTimeMs: number
  /** 版本追踪指纹（透传 request.codeFingerprint）。 */
  codeFingerprint?: string
}

/** 执行后端能力声明（Backend 实现方填写）。 */
export interface BackendCapabilities {
  /** 支持的语言 ID 列表。 */
  languages: string[]
  /** 是否支持多文件模块解析。 */
  multiFile: boolean
  /** 是否支持测试运行。 */
  testRunner: boolean
  /** 是否在浏览器内执行（vs 远程沙箱）。 */
  inBrowser: boolean
  /** 信任级别：浏览器内 = practice；远程可信执行 = formal。 */
  maxTrustLevel: TrustLevel
}
