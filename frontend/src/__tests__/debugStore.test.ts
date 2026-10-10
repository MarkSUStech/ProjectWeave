/** debugStore 行为测试：断点维护 / 启动门控 / 轮询收敛 / 命令 / 懒加载（mock API）。 */

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'

vi.mock('../api/debug', () => ({
  startDebugSession: vi.fn(),
  getDebugSnapshot: vi.fn(),
  sendDebugCommand: vi.fn(),
  stopDebugSession: vi.fn(),
  expandDebugVariables: vi.fn(),
}))

import { useDebugStore } from '../stores/debugStore'
import {
  getDebugSnapshot,
  sendDebugCommand,
  startDebugSession,
  stopDebugSession,
  expandDebugVariables,
} from '../api/debug'

const mockedStart = vi.mocked(startDebugSession)
const mockedGet = vi.mocked(getDebugSnapshot)
const mockedCommand = vi.mocked(sendDebugCommand)
const mockedStop = vi.mocked(stopDebugSession)
const mockedExpand = vi.mocked(expandDebugVariables)

function snapshot(overrides: Record<string, unknown> = {}) {
  return {
    id: '11111111-0000-4000-8000-000000000001',
    language: 'cpp', status: 'paused', endReason: null, entryPoint: 'src/main.cpp',
    projectId: null, codeFingerprint: null, debuggerProfile: 'lldb-dap:19',
    location: { file: 'src/main.cpp', line: 5, column: 1, frameName: 'main' },
    stopReason: 'breakpoint',
    threads: [{ id: 1, name: 'app', isPrimary: true }],
    stackFrames: [{ id: 0, name: 'main', file: 'src/main.cpp', line: 5, column: 1 }],
    scopes: [],
    breakpoints: [{ path: 'src/main.cpp', line: 5, verified: true, message: null }],
    buildDiagnostics: [], buildStdout: '', error: null, dapLog: [],
    sandbox: { engine: 'docker', image: null },
    createdAt: '2026-10-11T00:00:00Z', startedAt: null, pausedAt: null, finishedAt: null,
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.useFakeTimers()
  useDebugStore.setState({
    breakpoints: {}, snapshot: null, starting: false, commanding: false,
    error: null, expandedVars: {},
  })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('断点维护', () => {
  it('toggle 添加/移除并保持排序', () => {
    const { toggleBreakpoint } = useDebugStore.getState()
    toggleBreakpoint('src/main.cpp', 10)
    toggleBreakpoint('src/main.cpp', 5)
    expect(useDebugStore.getState().breakpoints['src/main.cpp']).toEqual([5, 10])
    toggleBreakpoint('src/main.cpp', 5)
    expect(useDebugStore.getState().breakpoints['src/main.cpp']).toEqual([10])
    toggleBreakpoint('src/main.cpp', 10)
    expect(useDebugStore.getState().breakpoints['src/main.cpp']).toBeUndefined()
    expect(useDebugStore.getState().hasBreakpoints()).toBe(false)
  })
})

describe('start 门控', () => {
  it('无断点拒绝启动并给出提示', async () => {
    await useDebugStore.getState().start({ entryPoint: 'a.cpp', files: { 'a.cpp': 'x' } })
    expect(useDebugStore.getState().error).toContain('断点')
    expect(mockedStart).not.toHaveBeenCalled()
  })

  it('503 错误如实呈现，不伪装成功', async () => {
    useDebugStore.getState().toggleBreakpoint('a.cpp', 3)
    mockedStart.mockRejectedValue(new Error('远程沙箱不可用：调试镜像不存在'))
    await useDebugStore.getState().start({ entryPoint: 'a.cpp', files: { 'a.cpp': 'int main(){}' } })
    expect(useDebugStore.getState().error).toContain('调试镜像不存在')
    expect(useDebugStore.getState().starting).toBe(false)
  })
})

describe('会话与轮询', () => {
  it('启动 → 轮询快照 → 终态停止轮询', async () => {
    useDebugStore.getState().toggleBreakpoint('src/main.cpp', 5)
    mockedStart.mockResolvedValue({ id: snapshot().id, status: 'creating' })
    mockedGet.mockResolvedValueOnce(snapshot({ status: 'configuring' }) as never)

    const promise = useDebugStore.getState().start({
      entryPoint: 'src/main.cpp', files: { 'src/main.cpp': 'int main(){}' },
    })
    await promise
    expect(useDebugStore.getState().snapshot?.status).toBe('configuring')

    // 轮询到 paused
    mockedGet.mockResolvedValueOnce(snapshot() as never)
    await vi.advanceTimersByTimeAsync(800)
    expect(useDebugStore.getState().snapshot?.status).toBe('paused')

    // 轮询到 terminated → 停止
    mockedGet.mockResolvedValueOnce(snapshot({ status: 'terminated', endReason: 'completed' }) as never)
    await vi.advanceTimersByTimeAsync(1600)
    expect(useDebugStore.getState().snapshot?.status).toBe('terminated')
    expect(mockedGet).toHaveBeenCalledTimes(3)
    // 终态后不再轮询
    await vi.advanceTimersByTimeAsync(3000)
    expect(mockedGet).toHaveBeenCalledTimes(3)
  })

  it('command 透传白名单指令并更新快照', async () => {
    useDebugStore.setState({ snapshot: snapshot() as never })
    mockedCommand.mockResolvedValue(snapshot({ status: 'paused', stopReason: 'step', location: { file: 'src/main.cpp', line: 6, column: 1, frameName: 'main' } }) as never)
    await useDebugStore.getState().command('next')
    expect(mockedCommand).toHaveBeenCalledWith(expect.any(String), 'next')
    expect(useDebugStore.getState().snapshot?.location?.line).toBe(6)
  })

  it('stop 调用停止端点', async () => {
    useDebugStore.setState({ snapshot: snapshot() as never })
    mockedStop.mockResolvedValue(snapshot({ status: 'terminated', endReason: 'cancelled' }) as never)
    await useDebugStore.getState().stop()
    expect(mockedStop).toHaveBeenCalledOnce()
    expect(useDebugStore.getState().snapshot?.endReason).toBe('cancelled')
  })

  it('expandVar 懒加载并缓存（重复点击不重复请求）', async () => {
    useDebugStore.setState({ snapshot: snapshot() as never })
    mockedExpand.mockResolvedValue({ variables: [{ name: 'inner', value: '7', type: null, variablesReference: 0 }] })
    await useDebugStore.getState().expandVar(3000)
    await useDebugStore.getState().expandVar(3000)
    expect(mockedExpand).toHaveBeenCalledOnce()
    expect(useDebugStore.getState().expandedVars[3000][0].name).toBe('inner')
  })

  it('会话中切换断点同步 setBreakpoints 指令', async () => {
    useDebugStore.setState({ snapshot: snapshot() as never, breakpoints: { 'src/main.cpp': [5] } })
    mockedCommand.mockResolvedValue(snapshot() as never)
    useDebugStore.getState().toggleBreakpoint('src/main.cpp', 9)
    await vi.waitFor(() => expect(mockedCommand).toHaveBeenCalled())
    const [, cmd, extra] = mockedCommand.mock.calls[0]
    expect(cmd).toBe('setBreakpoints')
    expect(extra?.breakpoints).toEqual([{ path: 'src/main.cpp', lines: [5, 9] }])
  })
})
