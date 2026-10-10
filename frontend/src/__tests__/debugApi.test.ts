/** 调试 API 客户端测试：schema 校验 + 调用路径（mock fetch）。 */

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'

import {
  debugSnapshotSchema,
  expandDebugVariables,
  getDebugSnapshot,
  sendDebugCommand,
  startDebugSession,
  stopDebugSession,
} from '../api/debug'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const FULL_SNAPSHOT = {
  id: '00000000-0000-4000-8000-000000000010',
  language: 'cpp',
  status: 'paused',
  endReason: null,
  entryPoint: 'src/main.cpp',
  projectId: null,
  codeFingerprint: 'abc123',
  debuggerProfile: 'lldb-dap:19',
  location: { file: 'src/main.cpp', line: 17, column: 27, frameName: 'main' },
  stopReason: 'breakpoint',
  threads: [{ id: 1, name: 'app', isPrimary: true }],
  stackFrames: [
    { id: 0, name: 'main', file: 'src/main.cpp', line: 17, column: 27 },
    { id: 1, name: '__libc_start_main', file: null, line: null, column: null },
  ],
  scopes: [
    {
      name: 'Locals', variablesReference: 1000, expensive: false,
      variables: [
        { name: 'x', value: '40', type: 'int', variablesReference: 0 },
        { name: 'box', value: '{a=1}', type: 'Box', variablesReference: 3000 },
      ],
    },
  ],
  breakpoints: [{ path: 'src/main.cpp', line: 17, verified: true, message: null }],
  buildDiagnostics: [],
  buildStdout: '',
  error: null,
  dapLog: [{ at: '2026-10-11T00:00:00Z', kind: 'event', detail: 'stopped' }],
  sandbox: { engine: 'docker', image: 'projectweave-sandbox-cpp-debug:clang19-trixie' },
  createdAt: '2026-10-11T00:00:00Z',
  startedAt: '2026-10-11T00:00:01Z',
  pausedAt: '2026-10-11T00:00:05Z',
  finishedAt: null,
}

describe('debugSnapshotSchema', () => {
  it('完整快照解析（缺省字段回落默认值）', () => {
    const parsed = debugSnapshotSchema.parse(FULL_SNAPSHOT)
    expect(parsed.location?.line).toBe(17)
    expect(parsed.stackFrames).toHaveLength(2)
    expect(parsed.scopes[0].variables[0].value).toBe('40')
    expect(parsed.debuggerProfile).toBe('lldb-dap:19')
  })

  it('最小快照（创建中）解析', () => {
    const parsed = debugSnapshotSchema.parse({
      id: '00000000-0000-4000-8000-000000000011',
      language: 'cpp', status: 'creating', entryPoint: 'a.cpp',
      createdAt: '2026-10-11T00:00:00Z',
    })
    expect(parsed.threads).toEqual([])
    expect(parsed.scopes).toEqual([])
    expect(parsed.location).toBeNull()
  })

  it('未知状态被拒绝', () => {
    expect(() => debugSnapshotSchema.parse({ ...FULL_SNAPSHOT, status: 'exploded' })).toThrow()
  })
})

describe('API 调用', () => {
  beforeEach(() => vi.stubGlobal('fetch', vi.fn()))
  afterEach(() => vi.unstubAllGlobals())

  it('startDebugSession POST /debug-sessions', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ id: FULL_SNAPSHOT.id, status: 'creating' }, 201))
    const result = await startDebugSession({
      entryPoint: 'src/main.cpp',
      files: { 'src/main.cpp': 'int main(){}' },
      breakpoints: [{ path: 'src/main.cpp', lines: [3] }],
    })
    expect(result.id).toBe(FULL_SNAPSHOT.id)
    expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain('/api/v1/debug-sessions')
    expect(vi.mocked(fetch).mock.calls[0][1]?.method).toBe('POST')
  })

  it('getDebugSnapshot / sendDebugCommand / stop / expand 路径', async () => {
    // 每次调用返回新的 Response（body 只能读一次）
    vi.mocked(fetch).mockImplementation(async () => jsonResponse(FULL_SNAPSHOT))
    await getDebugSnapshot(FULL_SNAPSHOT.id)
    expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain(`/api/v1/debug-sessions/${FULL_SNAPSHOT.id}`)

    await sendDebugCommand(FULL_SNAPSHOT.id, 'next')
    const [, init] = vi.mocked(fetch).mock.calls[1]
    expect(String(vi.mocked(fetch).mock.calls[1][0])).toContain('/commands')
    expect(JSON.parse(String(init?.body)).command).toBe('next')

    vi.mocked(fetch).mockImplementation(async () => jsonResponse({ variables: [{ name: 'a', value: '1', type: null, variablesReference: 0 }] }))
    const expanded = await expandDebugVariables(FULL_SNAPSHOT.id, 3000)
    expect(expanded.variables[0].name).toBe('a')
    expect(String(vi.mocked(fetch).mock.calls[2][0])).toContain('variablesReference=3000')

    vi.mocked(fetch).mockImplementation(async () => jsonResponse({ ...FULL_SNAPSHOT, status: 'terminated', endReason: 'cancelled' }))
    const stopped = await stopDebugSession(FULL_SNAPSHOT.id)
    expect(stopped.endReason).toBe('cancelled')
  })

  it('沙箱不可用 503 → ApiError 明确报错', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ detail: '调试镜像不存在：x' }, 503))
    await expect(
      startDebugSession({ entryPoint: 'a.cpp', files: { 'a.cpp': 'x' }, breakpoints: [{ path: 'a.cpp', lines: [1] }] }),
    ).rejects.toThrow('调试镜像不存在')
  })
})
