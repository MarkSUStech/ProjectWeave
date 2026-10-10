/** 测试套件编排（runTestSuite）与 testStore 测试。 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useTestStore } from '../stores/testStore'
import { useRunStore } from '../stores/runStore'
import type { FileMeta } from '../types/file'
import type { RunResult, TestCaseResult } from '../types/runner'

vi.mock('../api/files', () => ({
  readFile: vi.fn(),
}))
vi.mock('../lib/runner/runFile', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/runner/runFile')>()
  return { ...actual, prepareScript: vi.fn() }
})
vi.mock('../lib/runner/runJavaScript', () => ({
  runJavaScript: vi.fn(),
  runTests: vi.fn(),
}))

const { readFile } = await import('../api/files')
const { prepareScript } = await import('../lib/runner/runFile')
const { runTests } = await import('../lib/runner/runJavaScript')
const { runTestSuite } = await import('../lib/runner/runTestSuite')

const mockedRead = vi.mocked(readFile)
const mockedPrepare = vi.mocked(prepareScript)
const mockedRunTests = vi.mocked(runTests)

function meta(path: string): FileMeta {
  return { path, size: 10, updatedAt: '2026-10-10T04:00:00Z' }
}

function fakeOutcome(cases: TestCaseResult[], ok = true) {
  return {
    result: { ok, durationMs: 10 } satisfies RunResult,
    cases,
    summary: {
      type: 'test-summary' as const,
      total: cases.length,
      passed: cases.filter((c) => c.status === 'passed').length,
      failed: cases.filter((c) => c.status === 'failed').length,
    },
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  useTestStore.setState({ running: false, progress: null, results: [], lastRunAt: null })
  useRunStore.setState({ activeTab: 'terminal', entries: [], running: false })
  mockedPrepare.mockImplementation(async (_path, content) => ({
    status: 'ok' as const,
    code: content,
    transpiled: false,
  }))
})

describe('runTestSuite', () => {
  it('只挑选测试文件、逐个执行并聚合到 store', async () => {
    mockedRead.mockImplementation(async (_projectId, path) => ({
      path,
      content: `content-of-${path}`,
      updatedAt: 't',
    }))
    mockedRunTests
      .mockResolvedValueOnce(
        fakeOutcome([
          { name: 'a', status: 'passed', durationMs: 1 },
          { name: 'b', status: 'failed', error: 'boom', durationMs: 2 },
        ]),
      )
      .mockResolvedValueOnce(fakeOutcome([{ name: 'c', status: 'passed', durationMs: 1 }]))

    const files = [meta('src/main.ts'), meta('src/a.test.ts'), meta('README.md'), meta('src/b.test.js')]
    const summary = await runTestSuite('p1', files)

    expect(mockedRunTests).toHaveBeenCalledTimes(2)
    expect(mockedRunTests).toHaveBeenNthCalledWith(1, 'content-of-src/a.test.ts', expect.anything())
    expect(mockedRunTests).toHaveBeenNthCalledWith(2, 'content-of-src/b.test.js', expect.anything())

    expect(summary).toEqual({ totalFiles: 2, totalPassed: 2, totalFailed: 1, errorFiles: 0 })
    const state = useTestStore.getState()
    expect(state.running).toBe(false)
    expect(state.progress).toEqual({ done: 2, total: 2 })
    expect(state.results[0]).toMatchObject({ path: 'src/a.test.ts', status: 'failed' })
    expect(state.results[0].cases).toHaveLength(2)
    expect(state.results[1]).toMatchObject({ path: 'src/b.test.js', status: 'passed' })
    // 运行测试时自动切到测试页签
    expect(useRunStore.getState().activeTab).toBe('tests')
  })

  it('当前文件的未保存草稿优先于服务器内容', async () => {
    mockedRead.mockResolvedValue({ path: 'src/a.test.ts', content: 'saved', updatedAt: 't' })
    mockedRunTests.mockResolvedValue(fakeOutcome([]))

    await runTestSuite('p1', [meta('src/a.test.ts')], {
      currentDraft: { path: 'src/a.test.ts', content: 'draft-content' },
    })
    expect(mockedRunTests).toHaveBeenCalledWith('draft-content', expect.anything())
    expect(mockedRead).not.toHaveBeenCalled()
  })

  it('文件读取失败记为 error 且不中断其余文件', async () => {
    mockedRead.mockImplementation(async (_p, path) => {
      if (path === 'bad.test.ts') throw new Error('网络错误')
      return { path, content: 'ok', updatedAt: 't' }
    })
    mockedRunTests.mockResolvedValue(fakeOutcome([{ name: 'x', status: 'passed', durationMs: 1 }]))

    const summary = await runTestSuite('p1', [meta('bad.test.ts'), meta('good.test.ts')])
    expect(summary).toEqual({ totalFiles: 2, totalPassed: 1, totalFailed: 0, errorFiles: 1 })
    const results = useTestStore.getState().results
    expect(results[0]).toMatchObject({ path: 'bad.test.ts', status: 'error', error: '网络错误' })
    expect(results[1]).toMatchObject({ path: 'good.test.ts', status: 'passed' })
  })

  it('Worker 级失败（语法/超时）记为 error', async () => {
    mockedRead.mockResolvedValue({ path: 'x.test.ts', content: 'syntax!!', updatedAt: 't' })
    mockedRunTests.mockResolvedValue({
      result: { ok: false, durationMs: 9, error: 'Unexpected token' },
      cases: [],
      summary: undefined,
    })
    const summary = await runTestSuite('p1', [meta('x.test.ts')])
    expect(summary.errorFiles).toBe(1)
    expect(useTestStore.getState().results[0]).toMatchObject({ status: 'error', error: 'Unexpected token' })
  })

  it('没有测试文件时不进入运行状态', async () => {
    const summary = await runTestSuite('p1', [meta('src/main.ts'), meta('README.md')])
    expect(summary).toEqual({ totalFiles: 0, totalPassed: 0, totalFailed: 0, errorFiles: 0 })
    expect(useTestStore.getState().running).toBe(false)
    expect(mockedRunTests).not.toHaveBeenCalled()
  })

  it('已有套件运行中时拒绝并发', async () => {
    useTestStore.setState({ running: true })
    const summary = await runTestSuite('p1', [meta('a.test.ts')])
    expect(summary.totalFiles).toBe(1)
    expect(mockedRunTests).not.toHaveBeenCalled()
  })
})

describe('testStore', () => {
  it('appendFileResult 累积结果并推进进度', () => {
    const store = useTestStore.getState()
    store.resetResults(2)
    store.appendFileResult({ path: 'a.test.ts', status: 'passed', cases: [] })
    expect(useTestStore.getState().progress).toEqual({ done: 1, total: 2 })
    expect(useTestStore.getState().lastRunAt).not.toBeNull()
  })
})
