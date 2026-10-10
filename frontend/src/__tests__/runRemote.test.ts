/** 远程执行终端胶水测试：状态行、流式输出、trace 绑定、取消、错误呈现（mock 后端）。 */

import { describe, expect, it, vi, beforeEach } from 'vitest'

vi.mock('../lib/execution/backends/remotePython', () => ({
  executeRemoteWithStream: vi.fn(),
  cancelActiveRemoteExecution: vi.fn(async () => 'exec-1'),
  remoteExecutionErrorMessage: vi.fn((err: unknown) => (err instanceof Error ? err.message : String(err))),
  remotePythonBackendId: 'remote-pytest',
}))

import { runRemoteInTerminal, runRemoteTestsInTerminal, canRunPath, isAnyTestPath, stopRemoteExecution } from '../lib/runner/runRemote'
import { executeRemoteWithStream } from '../lib/execution/backends/remotePython'
import { useRunStore } from '../stores/runStore'
import { ApiError } from '../api/client'

const mockedExecute = vi.mocked(executeRemoteWithStream)

function okExtras(overrides: Record<string, unknown> = {}) {
  return {
    executionId: 'exec-abc',
    status: 'completed',
    exitCode: 0,
    timedOut: false,
    cancelled: false,
    runTimeMs: 120,
    ...overrides,
  }
}

function baseResult(overrides: Record<string, unknown> = {}) {
  return {
    ok: true,
    mode: 'run',
    buildDiagnostics: [],
    runtimeDiagnostics: [],
    output: [],
    modules: ['main.py'],
    buildTimeMs: 0,
    runTimeMs: 120,
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  useRunStore.getState().clear()
  useRunStore.setState({ running: false, stdin: '', activeExecutionId: null, trace: null })
})

describe('canRunPath / isAnyTestPath', () => {
  it('Python 与 TS 均可执行；Python 测试文件按 test_*.py 识别', () => {
    expect(canRunPath('src/main.ts')).toBe(true)
    expect(canRunPath('src/main.js')).toBe(true)
    expect(canRunPath('src/main.py')).toBe(true)
    expect(canRunPath('README.md')).toBe(false)
    expect(isAnyTestPath('src/a.test.ts')).toBe(true)
    expect(isAnyTestPath('tests/test_math.py')).toBe(true)
    expect(isAnyTestPath('src/mathlib.py')).toBe(false)
  })
})

describe('runRemoteInTerminal', () => {
  it('成功运行：状态行、流式输出、trace 含 executionId/backend', async () => {
    mockedExecute.mockImplementation(async (_req, onEvent, onCreated) => {
      onCreated?.('exec-abc')
      onEvent?.('stdout', 'hello world\n')
      onEvent?.('stderr', 'warn\n')
      return { ...baseResult(), extras: okExtras() } as never
    })
    const outcome = await runRemoteInTerminal('main.py', new Map([['main.py', "print('hello world')"]]), { projectId: 'p1' })

    expect(outcome.status).toBe('ok')
    expect(outcome.executionId).toBe('exec-abc')
    const entries = useRunStore.getState().entries.map((e) => `${e.kind}:${e.text}`)
    expect(entries.some((e) => e.includes('远程沙箱'))).toBe(true)
    expect(entries).toContain('log:hello world')
    expect(entries).toContain('error:warn')
    expect(entries.some((e) => e.startsWith('system:✔ 完成'))).toBe(true)
    const trace = useRunStore.getState().trace
    expect(trace?.backend).toBe('remote-pytest')
    expect(trace?.executionId).toBe('exec-abc')
    expect(trace?.runPath).toBe('main.py')
    expect(useRunStore.getState().running).toBe(false)
  })

  it('stdin 来自 runStore 并随请求提交', async () => {
    useRunStore.setState({ stdin: 'ProjectWeave' })
    mockedExecute.mockResolvedValue({ ...baseResult(), extras: okExtras() } as never)
    await runRemoteInTerminal('main.py', new Map([['main.py', 'input()']]))
    expect(mockedExecute.mock.calls[0][0].stdin).toBe('ProjectWeave')
  })

  it('超时：terminal 显示超时错误并返回 timeout 状态', async () => {
    mockedExecute.mockResolvedValue({
      ...baseResult({ ok: false }),
      extras: okExtras({ status: 'timed-out', timedOut: true, exitCode: null }),
    } as never)
    const outcome = await runRemoteInTerminal('loop.py', new Map([['loop.py', 'while True: pass']]))
    expect(outcome.status).toBe('timeout')
    const entries = useRunStore.getState().entries.map((e) => e.text)
    expect(entries.some((t) => t.includes('超时'))).toBe(true)
  })

  it('沙箱不可用：明确错误信息，不伪装成功', async () => {
    mockedExecute.mockRejectedValue(new ApiError(503, '远程沙箱不可用：Docker 不可达'))
    const outcome = await runRemoteInTerminal('main.py', new Map([['main.py', 'x']]))
    expect(outcome.status).toBe('error')
    const entries = useRunStore.getState().entries.map((e) => e.text)
    expect(entries.some((t) => t.includes('远程沙箱不可用'))).toBe(true)
    expect(useRunStore.getState().running).toBe(false)
  })

  it('并发拒绝：运行中再次运行直接返回错误', async () => {
    useRunStore.setState({ running: true })
    const outcome = await runRemoteInTerminal('main.py', new Map([['main.py', 'x']]))
    expect(outcome.status).toBe('error')
    expect(mockedExecute).not.toHaveBeenCalled()
  })
})

describe('runRemoteTestsInTerminal', () => {
  it('test 模式：入口无、测试文件列表提交', async () => {
    mockedExecute.mockResolvedValue({
      ...baseResult({ mode: 'test', ok: true, testResults: [{ path: 'test_a.py', status: 'passed', cases: [] }] }),
      extras: okExtras(),
    } as never)
    const outcome = await runRemoteTestsInTerminal(['test_a.py'], new Map([['test_a.py', 'def test_x(): pass']]))
    expect(outcome.status).toBe('ok')
    const req = mockedExecute.mock.calls[0][0]
    expect(req.mode).toBe('test')
    expect(req.testPaths).toEqual(['test_a.py'])
    expect(req.entryPoint).toBeUndefined()
    expect(useRunStore.getState().trace?.runPath).toBeNull()
  })
})

describe('stopRemoteExecution', () => {
  it('调用取消并提示', async () => {
    await stopRemoteExecution()
    const entries = useRunStore.getState().entries.map((e) => e.text)
    expect(entries.some((t) => t.includes('取消'))).toBe(true)
  })
})
