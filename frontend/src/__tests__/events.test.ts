/** 事件契约/API 测试与 eventTracker 测试（tracker 独立文件避免 mock 污染）。 */
import { afterEach, describe, expect, it, vi } from 'vitest'

// ---------- 契约与 API（不 mock） ----------

import { eventListSchema, ingestResultSchema } from '../types/event'
import { ingestEvents, listEvents } from '../api/events'

const event = {
  eventId: '11111111-1111-4111-8111-111111111111',
  schemaVersion: 1,
  type: 'code-run',
  occurredAt: '2026-10-10T11:00:00Z',
  aggregateId: 'project:p1',
  sequence: 3,
  projectId: null,
  payload: { path: 'a.ts', status: 'ok' },
}

describe('事件契约', () => {
  it('解析读取模型与上报结果', () => {
    expect(eventListSchema.parse({ items: [event], total: 1 }).items[0].sequence).toBe(3)
    expect(ingestResultSchema.parse({ accepted: 1, duplicated: 0 }).accepted).toBe(1)
  })
})

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

describe('事件 API 客户端', () => {
  it('ingestEvents POST 批量', async () => {
    const fetchMock = mockFetch(200, { accepted: 2, duplicated: 0 })
    vi.stubGlobal('fetch', fetchMock)
    const result = await ingestEvents([
      { eventId: 'e1', type: 'code-run', occurredAt: 't', aggregateId: 'project:p1', payload: {} },
      { eventId: 'e2', type: 'tests-run', occurredAt: 't', aggregateId: 'project:p1', payload: {} },
    ])
    expect(result.accepted).toBe(2)
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/v1/events')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string).events).toHaveLength(2)
  })

  it('listEvents 组合查询参数', async () => {
    const fetchMock = mockFetch(200, { items: [event], total: 1 })
    vi.stubGlobal('fetch', fetchMock)
    await listEvents('p1', 'code-run')
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/v1/events?projectId=p1&type=code-run')
  })
})
