/** 文件类型分发测试：.js 直跑、.ts 真编译器转译、其他拒绝。 */
import { describe, expect, it } from 'vitest'
import { runInNewContext } from 'node:vm'
import { buildWorkerSource } from '../lib/runner/workerSource'
import { extensionOf, isRunnablePath, prepareScript } from '../lib/runner/runFile'

describe('extensionOf / isRunnablePath', () => {
  it.each([
    ['src/a.js', 'js'],
    ['a.mjs', 'mjs'],
    ['folder.with.dots/a.ts', 'ts'],
    ['README.md', 'md'],
  ])('%s → %s', (path, expected) => {
    expect(extensionOf(path)).toBe(expected)
  })

  it.each([
    ['a.js', true],
    ['a.mjs', true],
    ['a.ts', true],
    ['a.mts', true],
    ['a.md', false],
    ['a.tsx', false],
    ['noext', false],
  ])('isRunnablePath(%s) = %s', (path, expected) => {
    expect(isRunnablePath(path)).toBe(expected)
  })
})

describe('prepareScript', () => {
  it('种子文件的 export 可真实执行，不依赖全局 exports，异步输出先于 done', async () => {
    const prepared = await prepareScript('main.ts', 'export function greet(name: string) { return `你好 ${name}` }; await Promise.resolve(); console.log(greet("Weave"));')
    const messages: { type: string; text?: string }[] = []
    const self = { postMessage: (message: { type: string; text?: string }) => messages.push(message), console: {} }
    await runInNewContext(buildWorkerSource(prepared.code), { self, console: { log: (...args: unknown[]) => self.postMessage({ type: 'console', text: args.join(' ') }) } })
    expect(messages.find((message) => message.type === 'console')?.text).toBe('你好 Weave')
    expect(messages.at(-1)?.type).toBe('done')
    expect(messages.some((message) => message.type === 'error')).toBe(false)
  })
  it('.js 原样返回且不标记转译', async () => {
    const prepared = await prepareScript('main.js', 'console.log(1)')
    expect(prepared).toEqual({ status: 'ok', code: 'console.log(1)', transpiled: false })
  })

  it('.ts 用真实编译器去除类型注解', async () => {
    const prepared = await prepareScript(
      'main.ts',
      'const answer: number = 42;\nfunction greet(name: string): string {\n  return `hi ${name}`;\n}\nconsole.log(greet("ts"));\nenum Color { Red, Green }\nconsole.log(Color.Green);',
    )
    expect(prepared.status).toBe('ok')
    expect(prepared.transpiled).toBe(true)
    expect(prepared.code).not.toContain(': number')
    expect(prepared.code).not.toContain(': string')
    // enum 被真实转译为 IIFE 结构
    expect(prepared.code).toContain('Color[Color["Green"]')
    expect(prepared.code).toContain('console.log(greet("ts"))')
  })

  it('不支持的类型明确拒绝并给出原因', async () => {
    const prepared = await prepareScript('README.md', '# hi')
    expect(prepared.status).toBe('unsupported')
    expect(prepared.reason).toContain('不支持 .md')
  })
})
