/** 知识图谱页渲染测试（mock API 模块，独立文件避免 vi.mock 提升污染）。 */
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ConceptsPage from '../pages/ConceptsPage'

vi.mock('../api/concepts', () => ({
  listConcepts: vi.fn(),
  getConcept: vi.fn(),
}))
vi.mock('../api/mastery', () => ({
  listMastery: vi.fn(),
}))

const { listConcepts } = await import('../api/concepts')
const { listMastery } = await import('../api/mastery')
const mocked = vi.mocked(listConcepts)
const mockedMastery = vi.mocked(listMastery)

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

beforeEach(() => {
  vi.clearAllMocks()
  mockedMastery.mockResolvedValue([])
})

describe('ConceptsPage', () => {
  it('显示掌握徽标：低置信为"尚不确定"，高置信显示百分比', async () => {
    mocked.mockResolvedValue({
      items: [
        concept,
        {
          ...concept,
          id: 'js.objects',
          title: '对象与引用',
          prerequisites: [],
        },
      ],
      domains: ['javascript'],
    })
    mockedMastery.mockResolvedValue([
      {
        conceptId: 'js.closures',
        dimensions: {
          understanding: { estimate: 0.9, confidence: 0.7, evidenceCount: 2, lastObservedAt: 't' },
        },
        modelVersion: 'rule-v1',
        updatedAt: 't',
      },
      {
        conceptId: 'js.objects',
        dimensions: {
          understanding: { estimate: 1, confidence: 0.5, evidenceCount: 1, lastObservedAt: 't' },
        },
        modelVersion: 'rule-v1',
        updatedAt: 't',
      },
    ])
    render(
      <MemoryRouter>
        <ConceptsPage />
      </MemoryRouter>,
    )
    expect(await screen.findByText(/理解 90%/)).toBeTruthy()
    expect(screen.getByText(/尚不确定（1 条证据）/)).toBeTruthy()
    // 无掌握记录的概念（如果存在）不显示徽标——此例两个概念都有记录，检查数量即可
    expect(screen.getAllByText(/条证据/)).toHaveLength(2)
  })

  it('掌握数据加载失败不影响概念列表', async () => {
    mocked.mockResolvedValue({ items: [concept], domains: ['javascript'] })
    mockedMastery.mockRejectedValue(new Error('down'))
    render(
      <MemoryRouter>
        <ConceptsPage />
      </MemoryRouter>,
    )
    expect(await screen.findByText('闭包与变量捕获')).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('按域分组渲染并展示先修信息', async () => {
    mocked.mockResolvedValue({
      items: [
        concept,
        {
          ...concept,
          id: 'ts.annotations',
          title: '类型注解基础',
          domain: 'typescript',
          prerequisites: [],
        },
      ],
      domains: ['javascript', 'typescript'],
    })
    render(
      <MemoryRouter>
        <ConceptsPage />
      </MemoryRouter>,
    )
    expect(await screen.findByText('闭包与变量捕获')).toBeTruthy()
    expect(screen.getByText('TypeScript')).toBeTruthy()
    expect(screen.getByText('先修 js.functions')).toBeTruthy()
    expect(screen.getByText('无先修 · 入口概念')).toBeTruthy()
  })

  it('空知识库显示空态', async () => {
    mocked.mockResolvedValue({ items: [], domains: [] })
    render(
      <MemoryRouter>
        <ConceptsPage />
      </MemoryRouter>,
    )
    expect(await screen.findByText('知识库为空')).toBeTruthy()
  })

  it('加载失败显示错误与重试', async () => {
    mocked.mockRejectedValue(new Error('down'))
    render(
      <MemoryRouter>
        <ConceptsPage />
      </MemoryRouter>,
    )
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByText('重试')).toBeTruthy()
  })
})
