/** 终端状态与 runToTerminal 粘合层测试。 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useRunStore } from '../stores/runStore'
import type { RunResult } from '../types/runner'

vi.mock('../lib/runner/runJavaScript', () => ({
  runJavaScript: vi.fn(),
}))
vi.mock('../lib/runner/runFile', () => ({
  prepareScript: vi.fn(),
  isRunnablePath: vi.fn(() => true),
}))

const { runJavaScript } = await import('../lib/runner/runJavaScript')
const { prepareScript } = await import('../lib/runner/runFile')
const { runFileInTerminal } = await import('../lib/runner/runToTerminal')

const mockedRun = vi.mocked(runJavaScript)
const mockedPrepare = vi.mocked(prepareScript)

beforeEach(() => {
  useRunStore.setState({ entries: [], running: false, activeTab: 'events' })
  vi.clearAllMocks()
})

describe('runStore', () => {
  it('appendEntry 追加并分配递增 id，clear 清空', () => {
    const store = useRunStore.getState()
    store.appendEntry('system', 'a')
    store.appendEntry('log', 'b')
    expect(useRunStore.getState().entries.map((e) => e.text)).toEqual(['a', 'b'])
    expect(useRunStore.getState().entries[1].kind).toBe('log')
    useRunStore.getState().clear()
    expect(useRunStore.getState().entries).toHaveLength(0)
  })

  it('超过 500 条时裁剪最早条目', () => {
    for (let i = 0; i < 505; i += 1) {
      useRunStore.getState().appendEntry('log', `line-${i}`)
    }
    const entries = useRunStore.getState().entries
    expect(entries).toHaveLength(500)
    expect(entries[0].text).toBe('line-5')
  })
})

describe('runFileInTerminal', () => {
  it('输出运行头、转译标注、流式条目与完成行', async () => {
    mockedPrepare.mockResolvedValue({ status: 'ok', code: 'transpiled-code', transpiled: true })
    mockedRun.mockImplementation(async (_code, options) => {
      options?.onEntry?.('log', '输出 A')
      options?.onEntry?.('error', '输出 B')
      return { ok: true, durationMs: 12 } satisfies RunResult
    })

    const { status } = await runFileInTerminal('src/main.ts', 'const a: number = 1;')
    expect(status).toBe('ok')
    expect(mockedRun).toHaveBeenCalledWith('transpiled-code', expect.anything())

    const entries = useRunStore.getState().entries
    expect(entries[0]).toMatchObject({ kind: 'system', text: expect.stringContaining('▶ 运行 src/main.ts') })
    expect(entries.some((e) => e.kind === 'system' && e.text.includes('转译'))).toBe(true)
    expect(entries.some((e) => e.kind === 'log' && e.text === '输出 A')).toBe(true)
    expect(entries.some((e) => e.kind === 'error' && e.text === '输出 B')).toBe(true)
    expect(entries.at(-1)).toMatchObject({ kind: 'system', text: expect.stringContaining('✔ 完成') })
    // 运行开始时自动切到终端页签
    expect(useRunStore.getState().activeTab).toBe('terminal')
    expect(useRunStore.getState().running).toBe(false)
  })

  it('不支持的文件类型写入错误行并返回 unsupported', async () => {
    mockedPrepare.mockResolvedValue({
      status: 'unsupported',
      code: '',
      transpiled: false,
      reason: '不支持 .md 文件',
    })
    const { status } = await runFileInTerminal('README.md', '# hi')
    expect(status).toBe('unsupported')
    expect(mockedRun).not.toHaveBeenCalled()
    const entries = useRunStore.getState().entries
    expect(entries.at(-1)).toMatchObject({ kind: 'error', text: expect.stringContaining('不支持 .md') })
  })

  it('运行失败时输出错误摘要并返回 error/timeout', async () => {
    mockedPrepare.mockResolvedValue({ status: 'ok', code: 'c', transpiled: false })
    mockedRun.mockResolvedValue({ ok: false, durationMs: 5001, error: '执行超时（>5000ms），已强制终止。' })
    const { status } = await runFileInTerminal('a.js', 'while(true){}')
    expect(status).toBe('timeout')
    expect(useRunStore.getState().entries.at(-1)?.text).toContain('超时')
  })

  it('已有运行进行中时拒绝并发运行', async () => {
    useRunStore.setState({ running: true })
    const { status } = await runFileInTerminal('a.js', 'x')
    expect(status).toBe('error')
    expect(mockedRun).not.toHaveBeenCalled()
  })
})
