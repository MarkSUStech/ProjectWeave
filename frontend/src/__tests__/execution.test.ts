/** 执行层契约测试：Profile 注册/检测、Backend 路由、Python/C++ 明确不支持。
 *
 * Worker 内部协议已由 runJavaScript.test.ts 覆盖；esbuild 打包由 bundler
 * 独立测试（需真实 WASM）。此处 mock Worker 层与 bundler，专注测试
 * 执行层的路由/编排/契约逻辑。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'

vi.mock('../lib/runner/runJavaScript', () => ({
  runJavaScript: vi.fn(),
  runTests: vi.fn(),
}))

// Mock bundler（esbuild-wasm 需要真实 WASM 文件，jsdom 环境不可用）
vi.mock('../lib/runner/bundler', () => ({
  bundleModule: vi.fn(),
  hasRelativeImports: vi.fn(),
}))

import {
  detectLanguage,
  execute,
  getProfile,
  isTestFile,
  listProfiles,
  UnsupportedExecutionError,
} from '../lib/execution'

const { runJavaScript, runTests } = await import('../lib/runner/runJavaScript')
const mockedRun = vi.mocked(runJavaScript)
const mockedRunTests = vi.mocked(runTests)
const { bundleModule, hasRelativeImports } = await import('../lib/runner/bundler')
const mockedBundle = vi.mocked(bundleModule)
const mockedHasImports = vi.mocked(hasRelativeImports)

describe('LanguageProfile', () => {
  it('TypeScript Profile 注册且元数据完整', () => {
    const ts = getProfile('typescript')
    expect(ts).toBeDefined()
    expect(ts!.sourceExtensions).toContain('ts')
    expect(ts!.supportedBackends).toContain('browser-worker')
  })

  it('Python Profile 已定义但无可用后端（不伪造）', () => {
    const py = getProfile('python')
    expect(py).toBeDefined()
    expect(py!.sourceExtensions).toContain('py')
    expect(py!.supportedBackends).toEqual([])
  })

  it('C++ Profile 已定义但无可用后端', () => {
    const cpp = getProfile('cpp')
    expect(cpp).toBeDefined()
    expect(cpp!.supportedBackends).toEqual([])
  })

  it('根据文件扩展名检测语言', () => {
    expect(detectLanguage('src/main.ts')).toBe('typescript')
    expect(detectLanguage('src/app.py')).toBe('python')
    expect(detectLanguage('src/main.cpp')).toBe('cpp')
    expect(detectLanguage('README.md')).toBeNull()
  })

  it('测试文件模式匹配', () => {
    expect(isTestFile('src/a.test.ts', 'typescript')).toBe(true)
    expect(isTestFile('src/a.ts', 'typescript')).toBe(false)
  })

  it('Profile 列表包含三种语言', () => {
    const ids = listProfiles().map((p) => p.languageId)
    expect(ids).toContain('typescript')
    expect(ids).toContain('python')
    expect(ids).toContain('cpp')
  })
})

describe('执行路由', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedHasImports.mockReturnValue(false)
    mockedRun.mockResolvedValue({ ok: true, durationMs: 10 })
  })

  it('TypeScript 单文件请求路由到 browser-worker 并返回结果', async () => {
    const vfs = new Map([['main.ts', 'console.log("hello")']])
    const result = await execute({
      mode: 'run', entryPoint: 'main.ts', files: vfs, languageId: 'typescript',
    })
    expect(result.ok).toBe(true)
    expect(result.mode).toBe('run')
    expect(mockedRun).toHaveBeenCalledOnce()
  })

  it('Python 请求抛出"无可用后端"（不伪造）', async () => {
    const vfs = new Map([['main.py', 'print("hello")']])
    await expect(
      execute({ mode: 'run', entryPoint: 'main.py', files: vfs, languageId: 'python' }),
    ).rejects.toThrow(UnsupportedExecutionError)
  })

  it('C++ 请求抛出"无可用后端"', async () => {
    const vfs = new Map([['main.cpp', 'int main() { return 0; }']])
    await expect(
      execute({ mode: 'run', entryPoint: 'main.cpp', files: vfs, languageId: 'cpp' }),
    ).rejects.toThrow(UnsupportedExecutionError)
  })

  it('未知语言抛出错误', async () => {
    await expect(
      execute({ mode: 'run', entryPoint: 'a.txt', files: new Map(), languageId: 'rust' }),
    ).rejects.toThrow(/未知语言/)
  })
})

describe('多文件 TypeScript 执行（验收 A/D/H）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedHasImports.mockReturnValue(true)
  })

  it('（验收 A）多文件打包后执行，模块列表正确', async () => {
    mockedBundle.mockResolvedValue({
      status: 'ok', code: 'console.log(3)', buildTimeMs: 42, modules: ['math.ts', 'main.ts'],
    })
    mockedRun.mockResolvedValue({ ok: true, durationMs: 5 })
    const vfs = new Map([
      ['math.ts', 'export function add(a,b){return a+b}'],
      ['main.ts', 'import { add } from "./math"; console.log(add(1,2));'],
    ])
    const result = await execute({
      mode: 'run', entryPoint: 'main.ts', files: vfs, languageId: 'typescript',
    })
    expect(result.ok).toBe(true)
    expect(result.modules).toContain('math.ts')
    expect(result.modules).toContain('main.ts')
    expect(result.buildTimeMs).toBe(42)
    expect(mockedBundle).toHaveBeenCalledWith('main.ts', vfs)
  })

  it('（验收 D）模块不存在 → 构建错误', async () => {
    mockedBundle.mockResolvedValue({
      status: 'error', code: '', buildTimeMs: 5,
      error: '模块不存在：./missing（从 main.ts 导入）', modules: [],
    })
    const vfs = new Map([['main.ts', 'import { nope } from "./missing";']])
    const result = await execute({
      mode: 'run', entryPoint: 'main.ts', files: vfs, languageId: 'typescript',
    })
    expect(result.ok).toBe(false)
    expect(result.buildDiagnostics).toHaveLength(1)
    expect(result.buildDiagnostics[0].source).toBe('build')
    expect(result.buildDiagnostics[0].file).toBe('main.ts')
  })

  it('（验收 H）外部 npm 包导入 → 构建错误', async () => {
    mockedBundle.mockResolvedValue({
      status: 'error', code: '', buildTimeMs: 5,
      error: '不支持外部包 "lodash"（仅支持项目内相对导入）', modules: [],
    })
    const vfs = new Map([['main.ts', 'import lodash from "lodash";']])
    const result = await execute({
      mode: 'run', entryPoint: 'main.ts', files: vfs, languageId: 'typescript',
    })
    expect(result.ok).toBe(false)
    expect(result.buildDiagnostics.some((d) => d.message.includes('外部包'))).toBe(true)
  })
})

describe('跨文件测试（验收 B/E）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedHasImports.mockReturnValue(true)
  })

  it('（验收 B）测试文件导入源码，逐用例结果正确', async () => {
    mockedBundle.mockResolvedValue({
      status: 'ok', code: 'describe(); it();', buildTimeMs: 20, modules: ['headings.ts', 'headings.test.ts'],
    })
    mockedRunTests.mockResolvedValue({
      result: { ok: true, durationMs: 8 },
      cases: [
        { name: '识别标题', status: 'passed' as const, durationMs: 2 },
        { name: '空输入', status: 'passed' as const, durationMs: 1 },
      ],
      summary: undefined,
    })
    const vfs = new Map([
      ['src/parser/headings.ts', 'export function parseHeadings(text) { return []; }'],
      ['src/parser/headings.test.ts', "import { parseHeadings } from './headings';\ndescribe('parseHeadings', () => { it('识别标题', () => {}); });"],
    ])
    const result = await execute({
      mode: 'test',
      testPaths: ['src/parser/headings.test.ts'],
      files: vfs,
      languageId: 'typescript',
    })
    expect(result.ok).toBe(true)
    expect(result.testResults).toBeDefined()
    expect(result.testResults![0].status).toBe('passed')
    expect(result.testResults![0].cases).toHaveLength(2)
    expect(result.testResults![0].cases.every((c) => c.status === 'passed')).toBe(true)
  })

  it('（验收 E）测试失败 → ok=false + 逐用例 failed', async () => {
    mockedBundle.mockResolvedValue({
      status: 'ok', code: 'describe();', buildTimeMs: 10, modules: ['a.ts', 'a.test.ts'],
    })
    mockedRunTests.mockResolvedValue({
      result: { ok: true, durationMs: 5 },
      cases: [
        { name: '通过', status: 'passed' as const, durationMs: 1 },
        { name: '失败', status: 'failed' as const, error: 'expected 1 to be 2', durationMs: 2 },
      ],
      summary: undefined,
    })
    const result = await execute({
      mode: 'test',
      testPaths: ['a.test.ts'],
      files: new Map([['a.ts', 'export const x=1'], ['a.test.ts', 'import { x } from "./a"']]),
      languageId: 'typescript',
    })
    expect(result.ok).toBe(false)
    expect(result.testResults![0].status).toBe('failed')
    expect(result.testResults![0].cases[1].error).toContain('expected 1 to be 2')
  })
})
