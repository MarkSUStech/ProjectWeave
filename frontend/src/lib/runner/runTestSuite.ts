/**
 * 测试套件编排：拉取项目全部测试文件，逐个在 Worker 沙箱中执行并聚合结果。
 *
 * - 从服务器读取已保存内容；当前打开文件若有未保存草稿则优先使用草稿
 *   （界面注明），避免“改了测试没保存”的困惑；
 * - `.ts` 测试文件同样经真实编译器转译（单文件、不检查类型）；
 * - 文件级错误（读取失败/转译不支持/语法错误/超时）如实记为 error，
 *   不伪装成通过。
 */

import { readFile } from '../../api/files'
import type { FileMeta } from '../../types/file'
import type { TestFileResult } from '../../types/runner'
import { useTestStore } from '../../stores/testStore'
import { useRunStore } from '../../stores/runStore'
import { fingerprint } from '../fingerprint'
import { isTestPath, prepareScript } from './runFile'
import { runTests } from './runJavaScript'

export interface TestSuiteSummary {
  totalFiles: number
  totalPassed: number
  totalFailed: number
  errorFiles: number
  /** 逐文件结果（P4.1：任务级评估需要）。 */
  files: Array<{
    path: string
    status: string
    passed: number
    failed: number
    totalCases: number
  }>
}

export interface RunTestSuiteOptions {
  timeoutMs?: number
  /** 当前打开文件的未保存草稿（若有），运行时优先于服务器内容。 */
  currentDraft?: { path: string; content: string }
  /** 测试注入用。 */
  loadContent?: (path: string) => Promise<string>
}

export async function runTestSuite(
  projectId: string,
  files: FileMeta[],
  options: RunTestSuiteOptions = {},
): Promise<TestSuiteSummary> {
  const testPaths = files.map((file) => file.path).filter(isTestPath)
  const store = useTestStore.getState()
  if (store.running || testPaths.length === 0) {
    return { totalFiles: testPaths.length, totalPassed: 0, totalFailed: 0, errorFiles: 0, files: [] }
  }

  useRunStore.getState().setActiveTab('tests')
  useTestStore.getState().setRunning(true)
  useTestStore.getState().resetResults(testPaths.length)

  // 版本绑定：traceId + 全部被执行内容（草稿优先）的联合指纹（§14.3）。
  const traceId = crypto.randomUUID()
  const executedContents: string[] = []
  const summary: TestSuiteSummary = { totalFiles: testPaths.length, totalPassed: 0, totalFailed: 0, errorFiles: 0, files: [] }

  for (const path of testPaths) {
    let result: TestFileResult
    try {
      const raw =
        options.currentDraft?.path === path
          ? options.currentDraft.content
          : await (options.loadContent
              ? options.loadContent(path)
              : readFile(projectId, path).then((file) => file.content))
      executedContents.push(`${path}\n${raw}`)
      const prepared = await prepareScript(path, raw)
      if (prepared.status === 'unsupported') {
        result = { path, status: 'error', error: prepared.reason, cases: [] }
      } else {
        const outcome = await runTests(prepared.code, {
          timeoutMs: options.timeoutMs,
          onEntry: (level, text) => useRunStore.getState().appendEntry(level, `[${path}] ${text}`),
        })
        if (!outcome.result.ok) {
          result = { path, status: 'error', error: outcome.result.error, cases: outcome.cases }
        } else {
          result = { path, status: outcome.cases.some((c) => c.status === 'failed') ? 'failed' : 'passed', cases: outcome.cases }
        }
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      result = { path, status: 'error', error: message, cases: [] }
    }

    summary.totalPassed += result.cases.filter((c) => c.status === 'passed').length
    summary.totalFailed += result.cases.filter((c) => c.status === 'failed').length
    if (result.status === 'error') summary.errorFiles += 1
    summary.files.push({
      path: result.path,
      status: result.status,
      passed: result.cases.filter((c) => c.status === 'passed').length,
      failed: result.cases.filter((c) => c.status === 'failed').length,
      totalCases: result.cases.length,
    })
    useTestStore.getState().appendFileResult(result)
  }

  useTestStore.getState().setRunning(false)
  useRunStore.getState().setTrace({
    traceId,
    fingerprint: await fingerprint(...executedContents),
    runPath: null,
    at: new Date().toISOString(),
  })
  return summary
}
