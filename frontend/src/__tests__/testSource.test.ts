/**
 * 测试运行时（buildTestSource）测试：在 node:vm 隔离全局中真实执行，
 * 验证用例收集、断言行为与消息协议（test-result → test-summary → done）。
 */
import { runInNewContext } from 'node:vm'
import { describe, expect, it } from 'vitest'
import { buildTestSource } from '../lib/runner/workerSource'

interface Message {
  type: string
  name?: string
  status?: string
  error?: string
  text?: string
  durationMs?: number
  total?: number
  passed?: number
  failed?: number
  message?: string
}

function executeTests(code: string): Promise<Message[]> {
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
    setTimeout: (fn: () => void, ms: number) => setTimeout(fn, ms),
  }
  sandbox.self = sandbox
  runInNewContext(buildTestSource(code), sandbox)
  return finished.then(() => messages)
}

const resultsOf = (messages: Message[]) => messages.filter((m) => m.type === 'test-result')

describe('buildTestSource（真实执行）', () => {
  it('注册、执行并发送 消息序列', async () => {
    const messages = await executeTests(`
      it('用例一', () => {})
      it('用例二', async () => { await new Promise(r => setTimeout(r, 2)) })
    `)
    expect(resultsOf(messages).map((m) => m.name)).toEqual(['用例一', '用例二'])
    expect(resultsOf(messages).every((m) => m.status === 'passed')).toBe(true)
    const summary = messages.find((m) => m.type === 'test-summary')!
    expect(summary).toMatchObject({ total: 2, passed: 2, failed: 0 })
    expect(messages.at(-1)).toMatchObject({ type: 'done' })
  })

  it('describe 前缀（含嵌套）', async () => {
    const messages = await executeTests(`
      describe('计算', () => {
        describe('加法', () => {
          it('1+1', () => {})
        })
        it('基础', () => {})
      })
    `)
    expect(resultsOf(messages).map((m) => m.name)).toEqual([
      '计算 › 加法 › 1+1',
      '计算 › 基础',
    ])
  })

  it('失败断言上报 error 且不影响后续用例', async () => {
    const messages = await executeTests(`
      it('失败的用例', () => { expect(1).toBe(2) })
      it('之后的用例', () => { expect(1).toBe(1) })
    `)
    const results = resultsOf(messages)
    expect(results[0]).toMatchObject({ status: 'failed' })
    expect(results[0].error).toContain('expected 1 to be 2')
    expect(results[1]).toMatchObject({ status: 'passed' })
    expect(messages.find((m) => m.type === 'test-summary')).toMatchObject({ total: 2, passed: 1, failed: 1 })
  })

  it('用例内未捕获异常计为失败', async () => {
    const messages = await executeTests(`it('抛错', () => { throw new Error('炸了') })`)
    expect(resultsOf(messages)[0]).toMatchObject({ status: 'failed' })
    expect(resultsOf(messages)[0].error).toContain('炸了')
  })

  it('断言：toEqual 深比较 / toContain / toThrow / truthy', async () => {
    const messages = await executeTests(`
      it('deep equal', () => { expect({ a: [1, { b: 2 }] }).toEqual({ a: [1, { b: 2 }] }) })
      it('toContain 字符串与数组', () => { expect('hello world').toContain('world'); expect([1, 2, 3]).toContain(2) })
      it('toThrow 匹配消息', () => { expect(() => { throw new Error('bad input') }).toThrow('input') })
      it('toBeTruthy / toBeFalsy', () => { expect(1).toBeTruthy(); expect(0).toBeFalsy() })
      it('toEqual 失败示例（应失败）', () => { expect({ a: 1 }).toEqual({ a: 2 }) })
    `)
    const results = resultsOf(messages)
    expect(results.slice(0, 4).every((m) => m.status === 'passed')).toBe(true)
    expect(results[4]).toMatchObject({ status: 'failed' })
    expect(results[4].error).toContain('deeply equal')
  })

  it('.not 反转断言', async () => {
    const messages = await executeTests(`
      it('not toBe', () => { expect(1).not.toBe(2) })
      it('not toContain', () => { expect([1, 2]).not.toContain(3) })
      it('not toBe 失败示例（应失败）', () => { expect(1).not.toBe(1) })
    `)
    const results = resultsOf(messages)
    expect(results[0]).toMatchObject({ status: 'passed' })
    expect(results[1]).toMatchObject({ status: 'passed' })
    expect(results[2]).toMatchObject({ status: 'failed' })
    expect(results[2].error).toContain('NOT to be')
  })

  it('测试代码里的 console 输出仍然流式回传', async () => {
    const messages = await executeTests(`
      it('打印', () => { console.log('来自测试的输出') })
    `)
    expect(messages.some((m) => m.type === 'console' && m.text === '来自测试的输出')).toBe(true)
  })

  it('注册阶段（顶层）异常直接上报 error', async () => {
    const messages = await executeTests(`throw new Error('注册失败')`)
    expect(messages.some((m) => m.type === 'error' && String(m.message).includes('注册失败'))).toBe(true)
    expect(resultsOf(messages)).toHaveLength(0)
  })

  it('test 是 it 的别名', async () => {
    const messages = await executeTests(`test('别名用例', () => {})`)
    expect(resultsOf(messages)[0]?.name).toBe('别名用例')
  })
})
