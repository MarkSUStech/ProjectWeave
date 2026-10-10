/** eventTracker 测试：批量触发、定时 flush、失败重试保留队列。 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api/events', () => ({
  ingestEvents: vi.fn(),
}))

const { ingestEvents } = await import('../api/events')
const mockedIngest = vi.mocked(ingestEvents)
const { trackClientEvent, flushEvents, pendingEvents, resetTracker } = await import(
  '../lib/eventTracker'
)

beforeEach(() => {
  vi.clearAllMocks()
  resetTracker()
  vi.useRealTimers()
})

afterEach(() => {
  vi.useRealTimers()
  resetTracker()
})

describe('eventTracker', () => {
  it('队列满 5 条自动批量上报', async () => {
    mockedIngest.mockResolvedValue({ accepted: 5, duplicated: 0 })
    for (let i = 0; i < 5; i += 1) {
      trackClientEvent('code-run', { i }, { projectId: 'p1' })
    }
    await vi.waitFor(() => expect(mockedIngest).toHaveBeenCalledTimes(1))
    const batch = mockedIngest.mock.calls[0][0]
    expect(batch).toHaveLength(5)
    expect(batch[0].type).toBe('code-run')
    expect(batch[0].aggregateId).toBe('project:p1')
    expect(batch[0].eventId).not.toBe(batch[1].eventId)
    expect(pendingEvents()).toHaveLength(0)
  })

  it('不足 5 条时由 30s 定时器触发', async () => {
    vi.useFakeTimers()
    mockedIngest.mockResolvedValue({ accepted: 1, duplicated: 0 })
    trackClientEvent('tests-run', { passed: 2 }, { projectId: 'p1' })
    expect(mockedIngest).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(30_000)
    expect(mockedIngest).toHaveBeenCalledTimes(1)
  })

  it('上报失败保留队列待重试（至少一次投递）', async () => {
    mockedIngest.mockRejectedValueOnce(new Error('network'))
    trackClientEvent('code-run', {}, { projectId: 'p1' })
    await flushEvents()
    expect(pendingEvents()).toHaveLength(1)

    mockedIngest.mockResolvedValue({ accepted: 1, duplicated: 0 })
    await flushEvents()
    expect(mockedIngest).toHaveBeenCalledTimes(2)
    expect(pendingEvents()).toHaveLength(0)
  })
})
