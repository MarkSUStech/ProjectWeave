/** 设置 API 测试。 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { getSettings, updateSettings } from '../api/settings'

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

describe('settings API', () => {
  it('getSettings 解析介入模式', async () => {
    const fetchMock = mockFetch(200, { interventionMode: 'guided' })
    vi.stubGlobal('fetch', fetchMock)
    expect(await getSettings()).toBe('guided')
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/settings', expect.anything())
  })

  it('updateSettings PATCH 并解析响应', async () => {
    const fetchMock = mockFetch(200, { interventionMode: 'quiet' })
    vi.stubGlobal('fetch', fetchMock)
    expect(await updateSettings('quiet')).toBe('quiet')
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/v1/settings')
    expect(init.method).toBe('PATCH')
    expect(JSON.parse(init.body as string)).toEqual({ interventionMode: 'quiet' })
  })

  it('非法模式值被 zod 拒绝', async () => {
    vi.stubGlobal('fetch', mockFetch(200, { interventionMode: 'loud' }))
    await expect(getSettings()).rejects.toThrow()
  })
})
