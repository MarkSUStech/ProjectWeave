/** 课程生成页测试（mock fetch）：入口/进度/分析/蓝图/发布交互。 */

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, Link: ({ children }: { children: React.ReactNode }) => <a>{children}</a> }
})

import CourseGeneratePage from '../pages/CourseGeneratePage'

const UUID = '11111111-0000-4000-8000-0000000000c0'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const generation = (overrides: Record<string, unknown> = {}) => ({
  id: UUID, source_url: 'https://github.com/karpathy/micrograd',
  status: 'fetching', stage: 'fetching', progress: 10,
  error: null, warnings: [], repo_owner: 'karpathy', repo_name: 'micrograd',
  commit_sha: 'a'.repeat(40), default_branch: 'master', license: { spdx: 'MIT' },
  stats: { textFiles: 8 }, repair_rounds: 0, published_at: null,
  created_at: '2026-10-11T00:00:00Z', updated_at: '2026-10-11T00:00:00Z',
  ...overrides,
})

const blueprint = {
  project: {
    title: '从零实现自动微分引擎', description: 'desc',
    source_url: 'https://github.com/karpathy/micrograd', commit_sha: 'a'.repeat(40),
    license: { spdx: 'MIT' }, tech_stack: ['Python'],
    final_artifact: '可训练 MLP', target_level: 'beginner', difficulty: 'medium',
    goals: [], non_goals: [], runtime_requirements: [], evidence: [],
  },
  milestones: [
    { milestoneId: 'ms-1', title: '数值基础', description: '', target_features: [],
      deliverables: ['Value'], depends_on: [], acceptance_criteria: ['加法'], estimated_effort_band: 'small' },
  ],
  tasks: [
    { taskId: 't1', milestoneId: 'ms-1', title: 'Value 与运算', description: '创建 Value',
      depends_on: [], required_concepts: [], learning_objectives: [], expected_files: [],
      deliverables: ['value.py'], acceptance_criteria: ['加法可运行'],
      test_strategy: '断言', hints_outline: [], source_evidence: [{ path: 'micrograd/engine.py', note: '参考', lines: '' }] },
  ],
  knowledge_requirements: [
    { concept_id: 'py.classes', title: '类', description: '', prerequisites: [], related_tasks: [], is_existing: false },
  ],
  blueprint_version: 1, generator_version: 'v1', generation_status: 'draft', warnings: [],
}

const analysis = {
  status: 'draft',
  analysis: {
    summary: '微型自动微分引擎', tech_stack: ['Python'], entry_points: [],
    modules: [{ statement: 'Value 标量自动微分', kind: 'confirmed', sources: [{ path: 'micrograd/engine.py' }] }],
    behaviors: [], tests_summary: '', dependencies: [], limitations: [], claims: [],
  },
  toolCalls: [{ tool: 'get_repository_metadata', ok: true, args: {} }],
}

const blueprintResp = {
  status: 'draft', blueprint,
  validation: { passed: true, issues: [], checked_at: '2026-10-11T00:00:00Z' },
}

let fetchImpl: (url: string, init?: RequestInit) => Promise<Response>

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => fetchImpl(url, init)))
})
afterEach(() => vi.unstubAllGlobals())

describe('CourseGeneratePage', () => {
  it('提交 URL → 轮询到 draft → 展示真实分析/蓝图/证据/发布', async () => {
    let polls = 0
    fetchImpl = async (url) => {
      if (url.endsWith('/course-generations') && !url.includes(UUID)) {
        return jsonResponse({ id: UUID, status: 'pending', progress: 0 }, 202)
      }
      if (url.includes(`/course-generations/${UUID}/analysis`)) return jsonResponse(analysis)
      if (url.includes(`/course-generations/${UUID}/blueprint`)) return jsonResponse(blueprintResp)
      if (url.includes(`/course-generations/${UUID}`)) {
        polls += 1
        return jsonResponse(generation(polls >= 2 ? { status: 'draft', stage: 'draft', progress: 100 } : {}))
      }
      return jsonResponse({}, 404)
    }
    render(<MemoryRouter><CourseGeneratePage /></MemoryRouter>)

    const input = screen.getByPlaceholderText(/micrograd/)
    fireEvent.change(input, { target: { value: 'https://github.com/karpathy/micrograd' } })
    fireEvent.click(screen.getByText('开始生成'))

    await waitFor(() => expect(screen.getByText(/karpathy\/micrograd/)).toBeTruthy(), { timeout: 3000 })
    await waitFor(() => expect(screen.getByText(/从零实现自动微分引擎/)).toBeTruthy(), { timeout: 3000 })
    // 分析摘要 + 证据分级徽标 + 任务证据
    expect(screen.getByText('微型自动微分引擎')).toBeTruthy()
    expect(screen.getByText('已证实')).toBeTruthy()
    screen.getByText(/Value 与运算/).click()
    expect(screen.getByText(/micrograd\/engine\.py/)).toBeTruthy()
    await waitFor(() => expect(screen.getByText('发布课程草稿')).toBeTruthy(), { timeout: 3000 })
  })

  it('失败状态显示错误与重试', async () => {
    fetchImpl = async (url) => {
      if (url.endsWith('/course-generations')) return jsonResponse({ id: UUID, status: 'pending', progress: 0 }, 202)
      if (url.includes('/analysis')) return jsonResponse({ status: 'failed', analysis: null, toolCalls: [] })
      if (url.includes('/blueprint')) return jsonResponse({ status: 'failed', blueprint: null, validation: null })
      return jsonResponse(generation({ status: 'failed', stage: 'fetching', error: '仓库不存在或不可访问（仅支持公开仓库）' }))
    }
    render(<MemoryRouter><CourseGeneratePage /></MemoryRouter>)
    const input = screen.getByPlaceholderText(/micrograd/)
    fireEvent.change(input, { target: { value: 'https://github.com/a/nope' } })
    fireEvent.click(screen.getByText('开始生成'))
    await waitFor(() => expect(screen.getByText(/仓库不存在/)).toBeTruthy(), { timeout: 3000 })
    expect(screen.getByText('重试')).toBeTruthy()
  })

  it('非法 URL 前端不提交（后端也会 422）', () => {
    render(<MemoryRouter><CourseGeneratePage /></MemoryRouter>)
    expect(screen.getByText('开始生成').hasAttribute('disabled')).toBe(true)
  })
})
