/** runTests 协议测试：FakeWorker 验证 test 事件转发与结束条件。 */
import { describe, expect, it, vi } from 'vitest'
import { runTests } from '../lib/runner/runJavaScript'

function makeFakeWorker() {
  const listeners: Record<string, Array<(e: unknown) => void>> = {}
  const worker = {
    addEventListener: (event: string, handler: (e: unknown) => void) => {
      ;(listeners[event] ??= []).push(handler)
    },
    postMessage: vi.fn(),
    terminate: vi.fn(),
  } as unknown as Worker
  return {
    worker,
    emitMessage: (data: unknown) => listeners['message']?.forEach((fn) => fn({ data })),
  }
}

describe('runTests', () => {
  it('转发 test-result / test-summary 并在 done 后结束', async () => {
    const fake = makeFakeWorker()
    const onTestCase = vi.fn()
    const promise = runTests('code', { createWorker: () => fake.worker, onTestCase, timeoutMs: 1000 })

    fake.emitMessage({ type: 'test-result', name: 'a', status: 'passed', durationMs: 3 })
    fake.emitMessage({ type: 'test-result', name: 'b', status: 'failed', error: 'boom', durationMs: 5 })
    fake.emitMessage({ type: 'test-summary', total: 2, passed: 1, failed: 1 })
    fake.emitMessage({ type: 'done', result: '2 tests' })

    const outcome = await promise
    expect(outcome.result.ok).toBe(true)
    expect(outcome.cases).toHaveLength(2)
    expect(outcome.cases[1]).toMatchObject({ name: 'b', status: 'failed', error: 'boom' })
    expect(outcome.summary).toMatchObject({ total: 2, passed: 1, failed: 1 })
    expect(onTestCase).toHaveBeenCalledTimes(2)
    expect(fake.worker.terminate).toHaveBeenCalled()
  })

  it('error 消息结束并保留已收到的用例', async () => {
    const fake = makeFakeWorker()
    const promise = runTests('code', { createWorker: () => fake.worker, timeoutMs: 1000 })
    fake.emitMessage({ type: 'test-result', name: 'a', status: 'passed', durationMs: 1 })
    fake.emitMessage({ type: 'error', message: 'Error: x' })
    const outcome = await promise
    expect(outcome.result.ok).toBe(false)
    expect(outcome.result.error).toContain('Error: x')
    expect(outcome.cases).toHaveLength(1)
  })
})
