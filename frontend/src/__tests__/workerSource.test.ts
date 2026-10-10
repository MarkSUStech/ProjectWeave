/**
 * worker 脚本文本测试：用 node:vm 创建真实隔离全局环境执行
 * buildWorkerSource 的产物——沙箱对象即全局（self 自引用），
 * 与真实 Worker 中 self === globalThis 的语义一致。
 */
import { runInNewContext } from 'node:vm'
import { describe, expect, it } from 'vitest'
import { buildWorkerSource } from '../lib/runner/workerSource'

interface Message {
  type: string
  level?: string
  text?: string
  message?: string
  result?: string
}

function executeInSandbox(code: string): Promise<Message[]> {
  const messages: Message[] = []
  let notify: () => void
  const finished = new Promise<void>((resolve) => {
    notify = resolve
  })
  const sandbox: Record<string, unknown> = {
    postMessage(raw: unknown) {
      const msg = raw as Message
      messages.push(msg)
      if (msg.type === 'done' || msg.type === 'error') notify()
    },
    // vm 上下文不包含 Node 定时器，显式提供
    setTimeout: (fn: () => void, ms: number) => setTimeout(fn, ms),
  }
  // self === 全局对象，模拟 Worker 环境
  sandbox.self = sandbox
  runInNewContext(buildWorkerSource(code), sandbox)
  return finished.then(() => messages)
}

describe('buildWorkerSource（真实执行）', () => {
  it('捕获 console.log 并发送 done', async () => {
    const messages = await executeInSandbox(`console.log('hello')`)
    expect(messages[0]).toMatchObject({ type: 'console', level: 'log', text: 'hello' })
    expect(messages.at(-1)).toMatchObject({ type: 'done' })
  })

  it('多参数合并、对象 JSON 序列化', async () => {
    const messages = await executeInSandbox(
      `console.log('obj', { a: 1, nested: { b: [1, 2] } })`,
    )
    expect(messages[0].text).toBe('obj {\n  "a": 1,\n  "nested": {\n    "b": [\n      1,\n      2\n    ]\n  }\n}')
  })

  it('warn/error/debug 映射到对应级别', async () => {
    const messages = await executeInSandbox(
      `console.warn('w'); console.error('e'); console.debug('d')`,
    )
    const levels = messages.filter((m) => m.type === 'console').map((m) => m.level)
    expect(levels).toEqual(['warn', 'error', 'log'])
  })

  it('循环引用序列化为 [Circular]', async () => {
    const messages = await executeInSandbox(
      `const a = {}; a.self = a; console.log(a)`,
    )
    expect(messages[0].text).toContain('[Circular]')
  })

  it('特殊值：null/undefined/函数/bigint', async () => {
    const messages = await executeInSandbox(
      'console.log(null, undefined, () => 1, 10n)',
    )
    expect(messages[0].text).toContain('null')
    expect(messages[0].text).toContain('undefined')
    expect(messages[0].text).toContain('ƒ')
    expect(messages[0].text).toContain('10n')
  })

  it('同步异常上报 error 且包含消息', async () => {
    const messages = await executeInSandbox(`throw new Error('boom')`)
    expect(messages.at(-1)).toMatchObject({ type: 'error' })
    expect(messages.at(-1)!.message).toContain('boom')
  })

  it('支持顶层 await，输出顺序保持', async () => {
    const messages = await executeInSandbox(
      `console.log('before'); await new Promise(r => setTimeout(r, 5)); console.log('after')`,
    )
    const texts = messages.filter((m) => m.type === 'console').map((m) => m.text)
    expect(texts).toEqual(['before', 'after'])
    expect(messages.at(-1)).toMatchObject({ type: 'done' })
  })
})
