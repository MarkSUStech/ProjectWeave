/** 学习者模型契约与 API 测试。 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { dimensionEstimateSchema, masteryListSchema } from '../types/mastery'
import { listMastery } from '../api/mastery'

const dimension = {
  estimate: 0.75,
  confidence: 0.7,
  evidenceCount: 2,
  lastObservedAt: '2026-10-10T09:00:00Z',
}

describe('mastery 契约', () => {
  it('解析合法估计', () => {
    expect(dimensionEstimateSchema.parse(dimension)).toEqual(dimension)
    const list = masteryListSchema.parse({
      items: [
        { conceptId: 'js.closures', dimensions: { understanding: dimension }, modelVersion: 'rule-v1', updatedAt: 't' },
      ],
      total: 1,
    })
    expect(list.items[0].dimensions.understanding.evidenceCount).toBe(2)
  })

  it('拒绝越界数值与非正证据数', () => {
    expect(() => dimensionEstimateSchema.parse({ ...dimension, estimate: 1.5 })).toThrow()
    expect(() => dimensionEstimateSchema.parse({ ...dimension, confidence: -0.1 })).toThrow()
    expect(() => dimensionEstimateSchema.parse({ ...dimension, evidenceCount: 0 })).toThrow()
  })
})

describe('mastery API', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('listMastery 指向 /mastery', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [], total: 0 }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const items = await listMastery()
    expect(items).toEqual([])
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/mastery', expect.anything())
  })
})
