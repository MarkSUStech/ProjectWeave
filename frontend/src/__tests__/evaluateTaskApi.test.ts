/** evaluateTask API 客户端测试（不 mock tasks 模块）。 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { evaluateTask } from '../api/tasks'

function mockFetch(status: number, body: unknown) {
  return vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('evaluateTask API 客户端', () => {
  it('POST 到任务 evaluate 端点并解析结果', async () => {
    const fetchMock = mockFetch(200, {
      taskId: 'task-scaffold',
      status: 'done',
      passed: true,
      rubricVersion: 'suite-green-v1',
      evidenceConcepts: ['browser.dom'],
    })
    vi.stubGlobal('fetch', fetchMock)
    const result = await evaluateTask('p1', 'task-scaffold', {
      files: [{ path: 'src/test.ts', status: 'passed', passed: 2, failed: 0, totalCases: 2 }], traceId: 't1',
    })
    expect(result.status).toBe('done')
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/v1/projects/p1/tasks/task-scaffold/evaluate')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string).traceId).toBe('t1')
  })

  it('拒绝非法 status 值', async () => {
    vi.stubGlobal('fetch', mockFetch(200, {
      taskId: 'x', status: 'vanished', passed: true, rubricVersion: 'v', evidenceConcepts: [],
    }))
    await expect(
      evaluateTask('p1', 'x', { files: [] }),
    ).rejects.toThrow()
  })
})
