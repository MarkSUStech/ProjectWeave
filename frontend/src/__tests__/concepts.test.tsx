/** 知识概念契约与 API 客户端测试（不 mock API 模块）。 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { conceptListSchema, conceptReadSchema } from '../types/concept'
import { getConcept, listConcepts } from '../api/concepts'

const concept = {
  id: 'js.closures',
  title: '闭包与变量捕获',
  domain: 'javascript',
  description: '函数与其词法环境的绑定。',
  prerequisites: ['js.functions', 'js.objects'],
  objectives: ['解释回调为何能访问外层变量'],
  assessmentMethods: ['prediction', 'explanation'],
  examples: ['事件回调中捕获当前笔记的 id'],
  version: 1,
  updatedAt: '2026-10-10T07:00:00Z',
}

describe('概念契约 schema', () => {
  it('解析合法概念', () => {
    expect(conceptReadSchema.parse(concept)).toEqual(concept)
    const list = conceptListSchema.parse({ items: [concept], total: 1, domains: ['javascript'] })
    expect(list.domains).toEqual(['javascript'])
  })

  it('拒绝缺失字段', () => {
    const { version: _omit, ...incomplete } = concept
    expect(() => conceptReadSchema.parse(incomplete)).toThrow()
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

describe('概念 API 客户端', () => {
  it('listConcepts 默认不带过滤、解析 domains', async () => {
    const fetchMock = mockFetch(200, { items: [concept], total: 1, domains: ['javascript'] })
    vi.stubGlobal('fetch', fetchMock)
    const result = await listConcepts()
    expect(result.items[0].id).toBe('js.closures')
    expect(result.domains).toEqual(['javascript'])
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/concepts', expect.anything())
  })

  it('listConcepts(domain) 编码查询参数', async () => {
    const fetchMock = mockFetch(200, { items: [], total: 0, domains: [] })
    vi.stubGlobal('fetch', fetchMock)
    await listConcepts('typescript')
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/v1/concepts?domain=typescript')
  })

  it('getConcept 对 id 做编码', async () => {
    const fetchMock = mockFetch(200, concept)
    vi.stubGlobal('fetch', fetchMock)
    await getConcept('js.closures')
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/concepts/js.closures', expect.anything())
  })
})
