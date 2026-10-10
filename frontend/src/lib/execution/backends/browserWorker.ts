/**
 * TypeScript/JavaScript 浏览器 Worker 执行后端（P4.2a 第一个完整实现）。
 *
 * 适配现有 runner 基础设施到 ExecutionBackend 接口：
 * - 多文件模式：esbuild-wasm 打包 → Worker 沙箱执行
 * - 单文件模式：ts-compiler 转译 → Worker 沙箱执行
 * - 测试模式：buildTestSource 注入测试运行时 → Worker 执行
 *
 * 信任级：practice（浏览器内执行，客户端自报结果）。
 */

import type {
  ConsoleOutput,
  Diagnostic,
  ExecutionRequest,
  ExecutionResult,
  TestFileOutcome,
} from '../types'
import type { ExecutionBackend } from '../ExecutionBackend'
import type { LanguageProfile } from '../LanguageProfile'

import { bundleModule, hasRelativeImports } from '../../runner/bundler'
import { runJavaScript, runTests } from '../../runner/runJavaScript'

export const browserWorkerBackendId = 'browser-worker'

/** 打包或转译源文件为可执行脚本。 */
async function prepareCode(
  entryPath: string,
  files: Map<string, string>,
): Promise<
  | { ok: true; code: string; buildTimeMs: number; modules: string[] }
  | { ok: false; diagnostics: Diagnostic[]; buildTimeMs: number }
> {
  const content = files.get(entryPath)
  if (content === undefined) {
    return {
      ok: false,
      buildTimeMs: 0,
      diagnostics: [
        { severity: 'error', message: `入口文件不存在：${entryPath}`, file: entryPath, source: 'build' },
      ],
    }
  }

  // 无相对 import → 单文件转译（更快）
  if (!hasRelativeImports(content) && !/(?:^|\n)\s*import\s+/.test(content)) {
    const ts = await import('ts-compiler')
    const start = performance.now()
    const output = ts.transpileModule(content, {
      compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS },
    })
    return {
      ok: true,
      code: output.outputText ?? '',
      buildTimeMs: Math.round(performance.now() - start),
      modules: [entryPath],
    }
  }

  // 有 import → esbuild-wasm 多文件打包
  const result = await bundleModule(entryPath, files)
  if (result.status === 'error') {
    return {
      ok: false,
      buildTimeMs: result.buildTimeMs,
      diagnostics: [
        { severity: 'error', message: result.error ?? '构建失败', file: entryPath, source: 'build' },
      ],
    }
  }
  return { ok: true, code: result.code, buildTimeMs: result.buildTimeMs, modules: result.modules }
}

async function doRun(
  request: ExecutionRequest,
  output: ConsoleOutput[],
  outputStart: number,
): Promise<ExecutionResult> {
  const entry = request.entryPoint ?? ''
  const prepared = await prepareCode(entry, request.files)
  if (!prepared.ok) {
    return {
      ok: false, mode: 'run',
      buildDiagnostics: prepared.diagnostics,
      runtimeDiagnostics: [], output,
      modules: [], buildTimeMs: prepared.buildTimeMs, runTimeMs: 0,
      codeFingerprint: request.codeFingerprint,
    }
  }

  const runStart = performance.now()
  const result = await runJavaScript(prepared.code, {
    timeoutMs: request.timeoutMs,
    onEntry: (level, text) => {
      output.push({ level, text, offsetMs: Math.round(performance.now() - outputStart) })
    },
    onObserved: (name, value) => {
      output.push({ level: 'log', text: `observe(${name}) = ${value}`, offsetMs: Math.round(performance.now() - outputStart) })
    },
  })

  const runtimeDiags: Diagnostic[] = []
  if (!result.ok && result.error) {
    runtimeDiags.push({ severity: 'error', message: result.error, file: entry, source: 'runtime' })
  }

  return {
    ok: result.ok, mode: 'run',
    buildDiagnostics: [], runtimeDiagnostics: runtimeDiags, output,
    modules: prepared.modules,
    buildTimeMs: prepared.buildTimeMs,
    runTimeMs: Math.round(performance.now() - runStart),
    codeFingerprint: request.codeFingerprint,
  }
}

async function doTest(
  request: ExecutionRequest,
  output: ConsoleOutput[],
  outputStart: number,
): Promise<ExecutionResult> {
  const testPaths = request.testPaths ?? []
  const testResults: TestFileOutcome[] = []
  const buildDiags: Diagnostic[] = []
  const runtimeDiags: Diagnostic[] = []
  let totalBuildMs = 0
  let totalRunMs = 0
  const allModules: string[] = []

  for (const testPath of testPaths) {
    const prepared = await prepareCode(testPath, request.files)
    if (!prepared.ok) {
      buildDiags.push(...prepared.diagnostics)
      testResults.push({ path: testPath, status: 'error', cases: [], error: prepared.diagnostics[0]?.message })
      totalBuildMs += prepared.buildTimeMs
      continue
    }
    totalBuildMs += prepared.buildTimeMs
    allModules.push(...prepared.modules)

    const runStart = performance.now()
    const outcome = await runTests(prepared.code, {
      timeoutMs: request.timeoutMs,
      onEntry: (level, text) => {
        output.push({ level, text: `[${testPath}] ${text}`, offsetMs: Math.round(performance.now() - outputStart) })
      },
    })
    totalRunMs += Math.round(performance.now() - runStart)

    if (!outcome.result.ok) {
      runtimeDiags.push({
        severity: 'error', message: outcome.result.error ?? '测试运行失败',
        file: testPath, source: 'runtime',
      })
      testResults.push({
        path: testPath, status: 'error',
        cases: outcome.cases.map((c) => ({ name: c.name, status: c.status, error: c.error, durationMs: c.durationMs })),
        error: outcome.result.error,
      })
    } else {
      testResults.push({
        path: testPath,
        status: outcome.cases.some((c) => c.status === 'failed') ? 'failed' : 'passed',
        cases: outcome.cases.map((c) => ({ name: c.name, status: c.status, error: c.error, durationMs: c.durationMs })),
      })
    }
  }

  return {
    ok: testResults.length > 0 && testResults.every((t) => t.status === 'passed'),
    mode: 'test',
    buildDiagnostics: buildDiags, runtimeDiagnostics: runtimeDiags,
    output, modules: allModules,
    testResults,
    buildTimeMs: totalBuildMs, runTimeMs: totalRunMs,
    codeFingerprint: request.codeFingerprint,
  }
}

export const browserWorkerBackend: ExecutionBackend = {
  backendId: browserWorkerBackendId,
  capabilities: {
    languages: ['typescript'],
    multiFile: true,
    testRunner: true,
    inBrowser: true,
    maxTrustLevel: 'practice',
  },

  canHandle(request: ExecutionRequest, profile: LanguageProfile): boolean {
    return (
      browserWorkerBackend.capabilities.languages.includes(request.languageId) &&
      profile.supportedBackends.includes(browserWorkerBackendId)
    )
  },

  async execute(request: ExecutionRequest): Promise<ExecutionResult> {
    const outputStart = performance.now()
    const output: ConsoleOutput[] = []
    if (request.mode === 'run') {
      return doRun(request, output, outputStart)
    }
    return doTest(request, output, outputStart)
  },
}

// 注册
import { registerBackend } from '../registry'
registerBackend(browserWorkerBackend)
