/** 课程规划契约与 API 客户端测试（不 mock plans 模块）。 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { planDetailSchema, planReadSchema } from '../types/plan'
import { getPlan, replan } from '../api/plans'

const plan = {
  id: '4e2d6f6e-1b1f-4c0f-9b8a-2f2f5c6a7b8d',
  projectId: '0e0f26b4-7e4d-4c8f-9d3a-2f4f5c6a7b8d',
  planVersion: 2,
  activities: [
    {
      type: 'learn-concept' as const,
      order: 1,
      conceptId: 'js.closures',
      taskId: 'task-input',
      title: null,
      reason: '先修补课，估计偏低（0.5）',
    },
    {
      type: 'practice-task' as const,
      order: 2,
      conceptId: null,
      taskId: 'task-scaffold',
      title: '建立页面骨架',
      reason: '里程碑 M1 交付：可打开的编辑器布局页面',
    },
  ],
  skipped: [{ conceptId: 'js.values-types', reason: '已掌握（估计 1.0，2 条证据）' }],
  reason: '基于学习证据生成（累计 16 条；掌握阈值 0.75 / 置信阈值 0.5）',
  createdAt: '2026-10-10T10:00:00Z',
}

describe('plan 契约', () => {
  it('解析合法 plan 与 detail', () => {
    expect(planReadSchema.parse(plan)).toEqual(plan)
    const detail = planDetailSchema.parse({
      plan,
      tasks: [{ taskId: 'task-scaffold', milestone: 1, title: '建立页面骨架', status: 'pending' }],
    })
    expect(detail.tasks).toHaveLength(1)
  })

  it('拒绝未知活动类型', () => {
    const bad = { ...plan, activities: [{ ...plan.activities[0], type: 'watch-video' }] }
    expect(() => planReadSchema.parse(bad)).toThrow()
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('plan API 客户端', () => {
  it('getPlan / replan 路径与方法', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            plan,
            tasks: [{ taskId: 'task-scaffold', milestone: 1, title: '建立页面骨架', status: 'pending' }],
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(plan), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
    vi.stubGlobal('fetch', fetchMock)
    const detail = await getPlan('p1')
    expect(detail.plan.planVersion).toBe(2)
    const updated = await replan('p1')
    expect(updated.planVersion).toBe(2)
    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/v1/plans/p1', expect.anything())
    const [secondUrl, secondInit] = fetchMock.mock.calls[1] as [string, RequestInit]
    expect(secondUrl).toBe('/api/v1/plans/p1/replan')
    expect(secondInit.method).toBe('POST')
  })
})
