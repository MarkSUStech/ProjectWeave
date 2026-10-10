/** 远程执行后端测试：轮询/结果映射/错误呈现（mock API 层，不发真实请求）。 */

import { describe, expect, it, vi, beforeEach } from 'vitest'

vi.mock('../api/executions', () => ({
  createExecution: vi.fn(),
  getExecution: vi.fn(),
  cancelExecution: vi.fn(),
  TERMINAL_STATUSES: new Set(['completed', 'failed', 'timed-out', 'cancelled']),
}))

import {
  executeRemoteWithStream,
  remoteExecutionErrorMessage,
  remotePythonBackend,
} from '../lib/execution/backends/remotePython'
import { createExecution, getExecution, cancelExecution } from '../api/executions'
import { ApiError } from '../api/client'

const mockedCreate = vi.mocked(createExecution)
const mockedGet = vi.mocked(getExecution)
const mockedCancel = vi.mocked(cancelExecution)

function snapshot(overrides: Record<string, unknown> = {}) {
  return {
    id: '00000000-0000-4000-8000-000000000001',
    language: 'python',
    mode: 'run',
    status: 'completed',
    entryPoint: 'main.py',
    testPaths: [],
    timeoutMs: 15000,
    codeFingerprint: null,
    projectId: null,
    exitCode: 0,
    timedOut: false,
    cancelled: false,
    error: null,
    stdout: 'hello\n',
    stderr: '',
    events: [
      { seq: 1, at: '2026-10-11T00:00:00Z', channel: 'stdout', text: 'hello\n' },
    ],
    diagnostics: [],
    testResults: null,
    phases: [{ name: 'run', status: 'completed', durationMs: 310, exitCode: 0 }],
    sandbox: { engine: 'docker', image: 'projectweave-sandbox-python:3.12', trustLevel: 'practice' },
    queuedAt: '2026-10-11T00:00:00Z',
    startedAt: '2026-10-11T00:00:01Z',
    finishedAt: '2026-10-11T00:00:02Z',
    runTimeMs: 310,
    ...overrides,
  }
}

const runRequest = {
  mode: 'run' as const,
  entryPoint: 'main.py',
  testPaths: [],
  files: new Map([['main.py', "print('hello')"]]),
  languageId: 'python',
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.useRealTimers()
})

describe('executeRemoteWithStream', () => {
  it('创建后轮询到终态，事件流式回传并映射结果', async () => {
    mockedCreate.mockResolvedValue({ id: '00000000-0000-4000-8000-000000000001', status: 'queued' })
    const running = snapshot({ status: 'running', events: [] })
    const done = snapshot({})
    mockedGet
      .mockResolvedValueOnce(running as never)
      .mockResolvedValueOnce(done as never)

    const events: Array<[string, string]> = []
    const created: string[] = []
    const returned = await executeRemoteWithStream(
      runRequest,
      (channel, text) => events.push([channel, text]),
      (id) => created.push(id),
    )

    expect(mockedCreate).toHaveBeenCalledOnce()
    expect(created).toEqual(['00000000-0000-4000-8000-000000000001'])
    // 增量轮询：第二次带 afterSeq=0（第一次无事件）
    expect(mockedGet).toHaveBeenNthCalledWith(1, '00000000-0000-4000-8000-000000000001', 0)
    expect(events).toEqual([['stdout', 'hello\n']])
    expect(returned.ok).toBe(true)
    expect(returned.output[0]).toEqual({ level: 'log', text: 'hello\n' })
    expect(returned.modules).toEqual(['main.py'])
    expect(returned.runTimeMs).toBe(310)
    expect(returned.extras.executionId).toBe('00000000-0000-4000-8000-000000000001')
    expect(returned.extras.exitCode).toBe(0)
    // 信任级如实为 practice（服务端执行 ≠ 正式认证）
    expect(remotePythonBackend.capabilities.maxTrustLevel).toBe('practice')
  })

  it('pytest 结果映射：error/skipped 用例归并为 failed，文件级 error 保留', async () => {
    mockedCreate.mockResolvedValue({ id: '00000000-0000-4000-8000-000000000002', status: 'queued' })
    mockedGet.mockResolvedValue(
      snapshot({
        id: '00000000-0000-4000-8000-000000000002',
        mode: 'test',
        status: 'completed',
        exitCode: 1,
        testResults: [
          {
            path: 'tests/test_math.py',
            status: 'failed',
            error: null,
            cases: [
              { name: 'test_add', status: 'passed', error: null, file: 'tests/test_math.py', line: 2, durationMs: 3 },
              { name: 'test_sub', status: 'failed', error: 'assert 3 == 2', file: 'tests/test_math.py', line: 6, durationMs: 2 },
              { name: 'test_skip', status: 'skipped', error: null, file: 'tests/test_math.py', line: 9, durationMs: 0 },
            ],
          },
          {
            path: 'tests/broken.py',
            status: 'error',
            error: 'ModuleNotFoundError: No module named x',
            cases: [],
          },
        ],
      }) as never,
    )
    const returned = await executeRemoteWithStream({ ...runRequest, mode: 'test', entryPoint: undefined, testPaths: ['tests/test_math.py', 'tests/broken.py'] })
    expect(returned.ok).toBe(false)
    expect(returned.testResults).toHaveLength(2)
    const cases = returned.testResults![0].cases
    expect(cases.map((c) => c.status)).toEqual(['passed', 'failed', 'failed'])
    expect(cases[1].error).toBe('assert 3 == 2')
    expect(returned.testResults![1].status).toBe('error')
  })

  it('超时终态 → ok=false 且诊断包含超时说明', async () => {
    mockedCreate.mockResolvedValue({ id: '00000000-0000-4000-8000-000000000003', status: 'queued' })
    mockedGet.mockResolvedValue(
      snapshot({ id: '00000000-0000-4000-8000-000000000003', status: 'timed-out', timedOut: true, exitCode: null }) as never,
    )
    const returned = await executeRemoteWithStream(runRequest)
    expect(returned.extras.timedOut).toBe(true)
    expect(returned.ok).toBe(false)
    expect(returned.runtimeDiagnostics.some((d) => d.message.includes('超时'))).toBe(true)
  })

  it('沙箱不可用（503）→ 抛出并转换为明确提示，不模拟成功', async () => {
    mockedCreate.mockRejectedValue(new ApiError(503, 'Docker 不可达。请安装并启动 Docker Desktop。'))
    await expect(executeRemoteWithStream(runRequest)).rejects.toThrow(/Docker 不可达/)
    expect(remoteExecutionErrorMessage(new ApiError(503, 'Docker 不可达'))).toContain('远程沙箱不可用')
  })

  it('轮询超时后请求取消并抛错', async () => {
    vi.useFakeTimers()
    mockedCreate.mockResolvedValue({ id: '00000000-0000-4000-8000-000000000004', status: 'queued' })
    // 立即返回 running（不挂起），让轮询循环只受 Date.now 截止时间驱动
    mockedGet.mockResolvedValue(snapshot({ status: 'running' }) as never)
    mockedCancel.mockResolvedValue({ id: '00000000-0000-4000-8000-000000000004', status: 'cancelled', alreadyFinished: false })
    const promise = executeRemoteWithStream(runRequest)
    const assertion = expect(promise).rejects.toThrow('轮询超时')
    await vi.advanceTimersByTimeAsync(185_000)
    await assertion
    expect(mockedCancel).toHaveBeenCalled()
    vi.useRealTimers()
  })
})
