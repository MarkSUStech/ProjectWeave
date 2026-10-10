/** API 客户端测试：请求构造、错误映射、网络失败提示。 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api } from '../api/client'

function mockFetch(status: number, body: unknown) {
  return vi.fn().mockResolvedValue(
    new Response(body === undefined ? null : JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('api client', () => {
  it('GET 请求指向 /api/v1 并解析 JSON', async () => {
    const fetchMock = mockFetch(200, { items: [], total: 0 })
    vi.stubGlobal('fetch', fetchMock)

    const data = await api.get<{ total: number }>('/projects')
    expect(data.total).toBe(0)
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/projects',
      expect.objectContaining({ headers: expect.objectContaining({ 'Content-Type': 'application/json' }) }),
    )
  })

  it('POST 携带 JSON 请求体', async () => {
    const fetchMock = mockFetch(201, { id: 'x' })
    vi.stubGlobal('fetch', fetchMock)

    await api.post('/projects', { title: '测试' })
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/v1/projects')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual({ title: '测试' })
  })

  it('非 2xx 响应映射为 ApiError 且保留 detail 信息', async () => {
    vi.stubGlobal('fetch', mockFetch(404, { detail: 'project not found' }))
    const err = await api.get('/projects/missing').catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).status).toBe(404)
    expect((err as ApiError).message).toBe('project not found')
  })

  it('无 detail 的错误使用通用消息', async () => {
    vi.stubGlobal('fetch', mockFetch(500, null))
    const err = await api.get('/projects').catch((e: unknown) => e)
    expect((err as ApiError).message).toBe('请求失败（HTTP 500）')
  })

  it('网络中断时抛出可读的连接错误', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('fetch failed')))
    const err = await api.get('/projects').catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).status).toBe(0)
    expect((err as ApiError).message).toContain('无法连接后端服务')
  })

  it('204 无内容返回 undefined', async () => {
    vi.stubGlobal('fetch', mockFetch(204, undefined))
    await expect(api.delete('/projects/x')).resolves.toBeUndefined()
  })
})
