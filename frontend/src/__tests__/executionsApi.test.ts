/** 远程执行 API 客户端测试：schema 校验 + fetch 封装行为（mock fetch）。 */

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'

import {
  cancelExecution,
  createExecution,
  executionSnapshotSchema,
  getExecution,
} from '../api/executions'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const FULL_SNAPSHOT = {
  id: '00000000-0000-4000-8000-000000000001',
  language: 'python',
  mode: 'run',
  status: 'completed',
  entryPoint: 'main.py',
  testPaths: [],
  timeoutMs: 15000,
  codeFingerprint: 'abc',
  projectId: null,
  exitCode: 0,
  timedOut: false,
  cancelled: false,
  error: null,
  stdout: 'hello',
  stderr: '',
  events: [{ seq: 1, at: '2026-10-11T00:00:00Z', channel: 'stdout', text: 'hello' }],
  diagnostics: [{ severity: 'error', message: 'boom', file: 'main.py', line: 3, column: null, source: 'runtime' }],
  testResults: null,
  phases: [{ name: 'run', status: 'completed', durationMs: 10, exitCode: 0 }],
  sandbox: { engine: 'docker', image: 'projectweave-sandbox-python:3.12', trustLevel: 'practice' },
  queuedAt: '2026-10-11T00:00:00Z',
  startedAt: '2026-10-11T00:00:01Z',
  finishedAt: '2026-10-11T00:00:02Z',
  runTimeMs: 1000,
}

describe('executionSnapshotSchema', () => {
  it('完整快照解析通过（默认值补齐可空字段）', () => {
    const parsed = executionSnapshotSchema.parse(FULL_SNAPSHOT)
    expect(parsed.status).toBe('completed')
    expect(parsed.sandbox.trustLevel).toBe('practice')
    expect(parsed.events[0].channel).toBe('stdout')
  })

  it('缺省字段回落默认值；未知状态被拒绝', () => {
    const minimal = {
      id: '00000000-0000-4000-8000-000000000002',
      language: 'python',
      mode: 'run',
      status: 'queued',
      timeoutMs: 5000,
      queuedAt: '2026-10-11T00:00:00Z',
    }
    const parsed = executionSnapshotSchema.parse(minimal)
    expect(parsed.events).toEqual([])
    expect(parsed.testResults).toBeNull()
    expect(parsed.sandbox.engine).toBeNull()

    expect(() => executionSnapshotSchema.parse({ ...minimal, status: 'exploded' })).toThrow()
  })
})

describe('API 调用', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('createExecution POST /executions 并校验响应', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ id: FULL_SNAPSHOT.id, status: 'queued' }, 202))
    const result = await createExecution({ language: 'python', mode: 'run', files: { 'main.py': 'x' } })
    expect(result.id).toBe(FULL_SNAPSHOT.id)
    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(String(url)).toContain('/api/v1/executions')
    expect(init?.method).toBe('POST')
  })

  it('getExecution 带 afterSeq 查询参数', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(FULL_SNAPSHOT))
    const snap = await getExecution(FULL_SNAPSHOT.id, 3)
    expect(snap.id).toBe(FULL_SNAPSHOT.id)
    expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain('afterSeq=3')
  })

  it('cancelExecution POST 取消端点', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ id: FULL_SNAPSHOT.id, status: 'cancelled', alreadyFinished: false }))
    const result = await cancelExecution(FULL_SNAPSHOT.id)
    expect(result.status).toBe('cancelled')
    expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain('/cancel')
  })

  it('503 沙箱不可用 → ApiError（不伪装成功）', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ detail: 'Docker 不可达' }, 503))
    await expect(
      createExecution({ language: 'python', mode: 'run', files: { 'main.py': 'x' } }),
    ).rejects.toThrow('Docker 不可达')
  })
})

// ---------------------------------------------------------------- P8.1 CMake profile 契约

describe('P8.1 CMake 执行契约', () => {
  it('cmake discover 快照解析：目标列表 + 生成器信息', () => {
    const parsed = executionSnapshotSchema.parse({
      ...FULL_SNAPSHOT,
      buildSystem: 'cmake',
      targetName: null,
      cmake: {
        operation: 'discover',
        targets: [
          {
            name: 'engine', type: 'STATIC_LIBRARY', runnable: false,
            sourceDirectory: 'engine', buildDirectory: 'build/engine',
            sources: ['engine/src/World.cpp'], artifacts: ['build/engine/libengine.a'],
            dependencies: [], configuration: 'Debug',
          },
          {
            name: 'game', type: 'EXECUTABLE', runnable: true,
            sourceDirectory: 'game', buildDirectory: 'build/game',
            sources: ['game/main.cpp'], artifacts: ['build/game/game'],
            dependencies: ['engine'], configuration: 'Debug',
          },
        ],
        discoveredTests: [],
        target: null, artifact: null,
        generator: 'Ninja', cmakeVersion: 'cmake version 3.25.1',
      },
    })
    expect(parsed.buildSystem).toBe('cmake')
    expect(parsed.cmake?.operation).toBe('discover')
    expect(parsed.cmake?.targets?.map((t) => t.name)).toEqual(['engine', 'game'])
    expect(parsed.cmake?.targets?.[1].dependencies).toEqual(['engine'])
  })

  it('ctest 结果：skipped 状态如实解析（未执行不得并入 failed/passed）', () => {
    const parsed = executionSnapshotSchema.parse({
      ...FULL_SNAPSHOT,
      mode: 'test',
      buildSystem: 'cmake',
      testResults: [
        { path: 'test_world', status: 'passed', cases: [{ name: 'test_world', status: 'passed', error: null, file: null, line: null, durationMs: 5 }], error: null },
        { path: 'test_terrain', status: 'skipped', cases: [{ name: 'test_terrain', status: 'skipped', error: '未执行（Not Run）', file: null, line: null, durationMs: 0 }], error: '未执行（Not Run）' },
      ],
      cmake: { operation: 'test', targets: null, discoveredTests: ['test_world', 'test_terrain'], target: null, artifact: null, generator: 'Ninja', cmakeVersion: 'cmake version 3.25.1' },
    })
    expect(parsed.testResults?.[1].status).toBe('skipped')
    expect(parsed.diagnostics[0].stage ?? null).toBe(null)
  })

  it('createExecution 透传 cmake 字段', async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      void init
      return jsonResponse({ id: FULL_SNAPSHOT.id, status: 'queued' }, 202)
    })
    vi.stubGlobal('fetch', fetchMock)
    try {
      await createExecution({
        language: 'cpp', mode: 'run', files: { 'CMakeLists.txt': '' },
        buildSystem: 'cmake', cmakeAction: 'run', targetName: 'game',
      })
      const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit | undefined)?.body as string)
      expect(body.buildSystem).toBe('cmake')
      expect(body.cmakeAction).toBe('run')
      expect(body.targetName).toBe('game')
    } finally {
      vi.unstubAllGlobals()
    }
  })
})
