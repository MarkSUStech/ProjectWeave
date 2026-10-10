/**
 * Execution Backend 接口：定义"在哪里、怎么执行代码"的策略。
 *
 * 实现方（如 browser-worker、remote-sandbox）只需实现此接口，
 * 并声明自己支持的语言列表。registry 负责路由。
 */

import type {
  BackendCapabilities,
  ExecutionRequest,
  ExecutionResult,
} from './types'
import type { LanguageProfile } from './LanguageProfile'

export interface ExecutionBackend {
  /** 后端唯一标识（如 'browser-worker', 'remote-sandbox'）。 */
  backendId: string
  /** 能力声明。 */
  capabilities: BackendCapabilities
  /** 判断能否处理给定请求。 */
  canHandle(request: ExecutionRequest, profile: LanguageProfile): boolean
  /** 执行请求，返回结果。 */
  execute(request: ExecutionRequest): Promise<ExecutionResult>
  /** 可选：预初始化（如加载 WASM 编译器）。 */
  prepare?(): Promise<void>
}
