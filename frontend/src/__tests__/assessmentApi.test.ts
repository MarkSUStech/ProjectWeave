/** 诊断契约与 API 客户端测试。 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  assessmentListSchema,
  assessmentSessionSchema,
} from '../types/assessment'
import {
  listProjectAssessments,
  startAssessment,
  submitAssessment,
} from '../api/assessments'

const session = {
  id: '3d2d6f6e-1b1f-4c0f-9b8a-2f2f5c6a7b8d',
  projectId: '0e0f26b4-7e4d-4c8f-9d3a-2f4f5c6a7b8d',
  status: 'in-progress',
  items: [
    {
      itemId: 'q.values-types-1',
      conceptId: 'js.values-types',
      prompt: 'typeof null ?',
      options: ["'null'", "'object'", "'undefined'", 'TypeError'],
      difficulty: 1,
    },
  ],
  results: null,
  createdAt: '2026-10-10T08:00:00Z',
  completedAt: null,
}

describe('诊断契约 schema', () => {
  it('解析进行中的会话', () => {
    expect(assessmentSessionSchema.parse(session)).toEqual(session)
  })

  it('解析含结果的会话', () => {
    const completed = {
      ...session,
      status: 'completed',
      completedAt: '2026-10-10T08:01:00Z',
      results: {
        concepts: [{ conceptId: 'js.values-types', label: 'likely-mastered', correctCount: 1, total: 1 }],
        questions: [
          {
            itemId: 'q.values-types-1',
            conceptId: 'js.values-types',
            correct: true,
            selectedOptionIndex: 1,
            correctOptionIndex: 1,
          },
        ],
      },
    }
    expect(assessmentSessionSchema.parse(completed).results?.concepts).toHaveLength(1)
  })

  it('拒绝非法 label', () => {
    const bad = {
      ...session,
      status: 'completed',
      results: {
        concepts: [{ conceptId: 'x', label: 'definitely', correctCount: 0, total: 1 }],
        questions: [],
      },
    }
    expect(() => assessmentSessionSchema.parse(bad)).toThrow()
  })

  it('列表契约', () => {
    const list = assessmentListSchema.parse({ items: [{ ...session, items: undefined as never }], total: 1 })
    expect(list.total).toBe(1)
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

describe('诊断 API 客户端', () => {
  it('startAssessment POST projectId', async () => {
    const fetchMock = mockFetch(201, session)
    vi.stubGlobal('fetch', fetchMock)
    await startAssessment('p1')
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/v1/assessments/start')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual({ projectId: 'p1' })
  })

  it('submitAssessment 携带 answers', async () => {
    const fetchMock = mockFetch(200, { ...session, status: 'completed' })
    vi.stubGlobal('fetch', fetchMock)
    await submitAssessment('s1', [{ itemId: 'q.values-types-1', selectedOptionIndex: 1 }])
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/v1/assessments/s1/submit')
    expect(JSON.parse(init.body as string)).toEqual({
      answers: [{ itemId: 'q.values-types-1', selectedOptionIndex: 1 }],
    })
  })

  it('listProjectAssessments 走项目嵌套路径', async () => {
    const fetchMock = mockFetch(200, { items: [], total: 0 })
    vi.stubGlobal('fetch', fetchMock)
    await listProjectAssessments('p9')
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/projects/p9/assessments', expect.anything())
  })
})
