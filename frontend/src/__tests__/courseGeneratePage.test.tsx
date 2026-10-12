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
  id: UUID, sourceUrl: 'https://github.com/karpathy/micrograd',
  status: 'fetching', stage: 'fetching', progress: 10,
  error: null, warnings: [], repoOwner: 'karpathy', repoName: 'micrograd',
  commitSha: 'a'.repeat(40), defaultBranch: 'master', license: { spdx: 'MIT' },
  stats: { textFiles: 8 }, repairRounds: 0, publishedAt: null,
  createdAt: '2026-10-11T00:00:00Z', updatedAt: '2026-10-11T00:00:00Z',
  ...overrides,
})

const blueprint = {
  project: {
    title: '从零实现自动微分引擎', description: 'desc',
    sourceUrl: 'https://github.com/karpathy/micrograd', commitSha: 'a'.repeat(40),
    license: { spdx: 'MIT' }, techStack: ['Python'],
    finalArtifact: '可训练 MLP', targetLevel: 'beginner', difficulty: 'medium',
    goals: [], nonGoals: [], runtimeRequirements: [], evidence: [],
  },
  milestones: [
    { milestoneId: 'ms-1', title: '数值基础', description: '', targetFeatures: [],
      deliverables: ['Value'], dependsOn: [], acceptanceCriteria: ['加法'], estimatedEffortBand: 'small' },
  ],
  tasks: [
    { taskId: 't1', milestoneId: 'ms-1', title: 'Value 与运算', description: '创建 Value',
      dependsOn: [], requiredConcepts: [], learningObjectives: [], expectedFiles: [],
      deliverables: ['value.py'], acceptanceCriteria: ['加法可运行'],
      testStrategy: '断言', hintsOutline: [], sourceEvidence: [{ path: 'micrograd/engine.py', note: '参考', lines: '' }] },
  ],
  knowledgeRequirements: [
    { conceptId: 'py.classes', title: '类', description: '', prerequisites: [], relatedTasks: [], isExisting: false },
  ],
  blueprintVersion: 1, generatorVersion: 'v1', generationStatus: 'draft', warnings: [],
}

const analysis = {
  status: 'draft',
  analysis: {
    summary: '微型自动微分引擎', techStack: ['Python'], entryPoints: [],
    modules: [{ statement: 'Value 标量自动微分', kind: 'confirmed', sources: [{ path: 'micrograd/engine.py' }] }],
    behaviors: [], testsSummary: '', dependencies: [], limitations: [], claims: [],
  },
  toolCalls: [{ tool: 'get_repository_metadata', ok: true, args: {} }],
}

const blueprintResp = {
  status: 'draft', blueprint,
  validation: { passed: true, issues: [], checkedAt: '2026-10-11T00:00:00Z' },
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

  it('release 失败 → 重试按钮 → 再次 build-lessons（v2）', async () => {
    const releaseBody = (version: number, status: string) => ({
      id: UUID, generationId: UUID, releaseVersion: version, status,
      language: 'python', totalTasks: 8, passedTasks: 3, failedTasks: 1,
      progress: status === 'failed' ? 100 : 5, currentTask: 'task-4-1',
      error: status === 'failed' ? '任务 task-4-1 验证失败：防伪守卫：starter 缺少 TODO 标记' : null,
      courseTitle: '从零实现自动微分引擎', readyAt: null,
      createdAt: '2026-10-11T00:00:00Z',
      artifacts: status === 'failed' ? [{
        taskId: 'task-4-1', milestoneId: 'ms-4', language: 'python',
        instructions: { title: '实现反向传播' },
        starterFiles: [], testFiles: [], hints: [], status: 'failed',
        verifications: [],
        repairs: [{ round: 1, problem: '防伪守卫：starter 缺少有效 TODO 标记', changedFiles: [], outcome: 'still-failing' }],
        error: '防伪守卫：starter 缺少有效 TODO 标记',
      }] : [],
    })
    let builds = 0
    fetchImpl = async (url, init) => {
      if (url.endsWith('/course-generations') && init?.method === 'POST') {
        return jsonResponse({ id: UUID, status: 'pending', progress: 0 }, 202)
      }
      if (url.endsWith('/build-lessons') && init?.method === 'POST') {
        builds += 1
        // 真实时序：POST 返回 generating 摘要（无 artifacts），轮询 GET 拿失败详情
        return jsonResponse(releaseBody(builds, 'generating'), 202)
      }
      if (url.includes('/course-releases/')) {
        return jsonResponse(releaseBody(1, 'failed'))
      }
      if (url.includes(`/course-generations/${UUID}/analysis`)) {
        return jsonResponse({ status: 'published', analysis: null, toolCalls: [] })
      }
      if (url.includes(`/course-generations/${UUID}/blueprint`)) {
        return jsonResponse({ status: 'published', blueprint: null, validation: null })
      }
      if (url.includes(`/course-generations/${UUID}`)) {
        return jsonResponse(generation({ status: 'published', stage: 'published', progress: 100 }))
      }
      return jsonResponse({}, 404)
    }
    render(<MemoryRouter><CourseGeneratePage /></MemoryRouter>)
    const input = screen.getByPlaceholderText(/micrograd/)
    fireEvent.change(input, { target: { value: 'https://github.com/karpathy/micrograd' } })
    fireEvent.click(screen.getByText('开始生成'))

    await waitFor(() => expect(screen.getByText('生成课程内容并验证')).toBeTruthy(), { timeout: 3000 })
    fireEvent.click(screen.getByText('生成课程内容并验证'))

    // 轮询拿到失败详情：错误横幅 + 每轮修复实际原因 + 重试按钮
    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy(), { timeout: 8000 })
    expect(screen.getByText(/修复尝试记录/)).toBeTruthy()
    expect(screen.getByText(/防伪守卫：starter 缺少有效 TODO 标记/)).toBeTruthy()
    expect(screen.getByText(/重新生成课程内容（v2）/)).toBeTruthy()
    expect(screen.getByText(/上次失败的具体原因会反馈给本次生成/)).toBeTruthy()

    fireEvent.click(screen.getByText(/重新生成课程内容（v2）/))
    await waitFor(() => expect(builds).toBe(2), { timeout: 3000 })
  }, 20000)
})
