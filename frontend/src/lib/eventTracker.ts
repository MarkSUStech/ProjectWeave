/**
 * 客户端学习事件追踪：批量缓冲 + 定时/定量 flush（设计 §11.3/§13.1）。
 *
 * - 事件先入内存队列，满 BATCH_SIZE 或每 FLUSH_MS 上报一次；
 * - 上报失败保留队列随下次重试（至少一次投递），服务端按 eventId 幂等去重；
 * - 队列上限 MAX_QUEUE，超限丢弃最旧（防御内存膨胀）；
 * - 刷新页面可能丢失未 flush 的事件（尽力而为，MVP 已知限制）。
 */
import { ingestEvents, type EventEnvelope } from '../api/events'
import type { ClientEventType } from '../types/event'

const BATCH_SIZE = 5
const FLUSH_MS = 30_000
const MAX_QUEUE = 50

let queue: EventEnvelope[] = []
let timer: ReturnType<typeof setInterval> | null = null

function newEventId(): string {
  return crypto.randomUUID()
}

export function trackClientEvent(
  type: ClientEventType,
  payload: Record<string, unknown>,
  context: { projectId: string },
): void {
  queue.push({
    eventId: newEventId(),
    type,
    occurredAt: new Date().toISOString(),
    aggregateId: `project:${context.projectId}`,
    projectId: context.projectId,
    payload,
  })
  if (queue.length > MAX_QUEUE) {
    queue = queue.slice(-MAX_QUEUE)
  }
  if (queue.length >= BATCH_SIZE) {
    void flushEvents()
  } else {
    ensureTimer()
  }
}

function ensureTimer(): void {
  if (timer === null && typeof window !== 'undefined') {
    timer = setInterval(() => void flushEvents(), FLUSH_MS)
  }
}

export async function flushEvents(): Promise<void> {
  if (timer !== null) {
    clearInterval(timer)
    timer = null
  }
  if (queue.length === 0) return
  const batch = queue
  queue = []
  try {
    await ingestEvents(batch)
  } catch {
    // 至少一次投递：失败放回队列等待下次（保留较新的一半防膨胀）
    queue = [...batch.slice(-MAX_QUEUE / 2), ...queue].slice(-MAX_QUEUE)
  }
}

/** 仅测试用：查看当前队列。 */
export function pendingEvents(): EventEnvelope[] {
  return [...queue]
}

/** 仅测试用：清空队列与定时器。 */
export function resetTracker(): void {
  queue = []
  if (timer !== null) {
    clearInterval(timer)
    timer = null
  }
}
