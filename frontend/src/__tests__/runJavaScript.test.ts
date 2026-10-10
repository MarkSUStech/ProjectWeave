/** runJavaScript 编排逻辑测试：注入 FakeWorker 验证协议、流式输出与超时。 */
import { describe, expect, it, vi } from 'vitest'
import { runJavaScript } from '../lib/runner/runJavaScript'

interface FakeWorker {
  worker: Worker
  emit: (event: 'message' | 'error', payload: unknown) => void
}

function makeFakeWorker(): FakeWorker {
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
    emit: (event, payload) => {
      listeners[event]?.forEach((handler) =>
        handler(
          event === 'message'
            ? { data: payload }
            : new ErrorEvent('error', { message: String(payload) }),
        ),
      )
    },
  }
}

describe('runJavaScript', () => {
  it('流式转发 console 输出并正常结束', async () => {
    const fake = makeFakeWorker()
    const onEntry = vi.fn()
    const promise = runJavaScript('code', {
      createWorker: () => fake.worker,
      onEntry,
      timeoutMs: 1000,
    })
    fake.emit('message', { type: 'console', level: 'log', text: '第一行' })
    fake.emit('message', { type: 'console', level: 'warn', text: '第二行' })
    fake.emit('message', { type: 'done', result: 'undefined' })
    const result = await promise
    expect(result.ok).toBe(true)
    expect(result.durationMs).toBeGreaterThanOrEqual(0)
    expect(onEntry.mock.calls.map((c) => c[1])).toEqual(['第一行', '第二行'])
    expect(fake.worker.terminate).toHaveBeenCalled()
  })

  it('流式转发 observe 变量观察', async () => {
    const fake = makeFakeWorker()
    const onObserved = vi.fn()
    const promise = runJavaScript('code', {
      createWorker: () => fake.worker,
      onObserved,
      timeoutMs: 1000,
    })
    fake.emit('message', { type: 'observed', name: 'count', text: '1' })
    fake.emit('message', { type: 'observed', name: 'count', text: '2' })
    fake.emit('message', { type: 'done', result: 'undefined' })
    await promise
    expect(onObserved.mock.calls).toEqual([
      ['count', '1'],
      ['count', '2'],
    ])
  })

  it('用户异常返回 ok=false 与错误信息', async () => {
    const fake = makeFakeWorker()
    const promise = runJavaScript('code', { createWorker: () => fake.worker, timeoutMs: 1000 })
    fake.emit('message', { type: 'error', message: 'Error: boom\n    at <anonymous>' })
    const result = await promise
    expect(result.ok).toBe(false)
    expect(result.error).toContain('boom')
    expect(fake.worker.terminate).toHaveBeenCalled()
  })

  it('脚本加载失败（error 事件）返回错误', async () => {
    const fake = makeFakeWorker()
    const promise = runJavaScript('code', { createWorker: () => fake.worker, timeoutMs: 1000 })
    fake.emit('error', 'Unexpected token')
    const result = await promise
    expect(result.ok).toBe(false)
    expect(result.error).toContain('Unexpected token')
  })

  it('超时强制终止并返回超时错误', async () => {
    vi.useFakeTimers()
    try {
      const fake = makeFakeWorker()
      const promise = runJavaScript('while(true){}', {
        createWorker: () => fake.worker,
        timeoutMs: 50,
      })
      await vi.advanceTimersByTimeAsync(60)
      const result = await promise
      expect(result.ok).toBe(false)
      expect(result.error).toContain('超时')
      expect(fake.worker.terminate).toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })

  it('worker 创建失败时立即返回错误', async () => {
    const result = await runJavaScript('code', {
      createWorker: () => {
        throw new Error('no worker')
      },
    })
    expect(result.ok).toBe(false)
    expect(result.error).toContain('无法创建运行环境')
  })
})
