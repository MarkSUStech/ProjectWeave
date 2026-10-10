/**
 * 执行层统一入口：导入此模块即完成 Profile + Backend 注册。
 *
 * 使用方式：
 * ```ts
 * import { execute } from '../lib/execution'
 * const result = await execute({
 *   mode: 'test',
 *   testPaths: ['src/parser/headings.test.ts'],
 *   files: vfs,
 *   languageId: 'typescript',
 * })
 * ```
 */

export * from './types'
export { registerProfile, getProfile, listProfiles, detectLanguage, isTestFile } from './LanguageProfile'
export type { LanguageProfile } from './LanguageProfile'
export type { ExecutionBackend } from './ExecutionBackend'
export { registerBackend, getBackend, selectBackend, execute, UnsupportedExecutionError } from './registry'

// 注册 TypeScript 浏览器后端（副作用导入）
import './backends/browserWorker'
