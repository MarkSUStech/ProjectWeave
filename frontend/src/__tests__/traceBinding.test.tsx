/** §14.3 版本绑定测试：指纹确定性、运行 trace 写入、事件 payload、过期横幅。 */
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fingerprint, shortFingerprint } from '../lib/fingerprint'

describe('fingerprint 工具', () => {
  it('确定性：同输入同指纹，内容变化即变', async () => {
    const a1 = await fingerprint('a.ts', 'const x = 1;')
    const a2 = await fingerprint('a.ts', 'const x = 1;')
    const b = await fingerprint('a.ts', 'const x = 2;')
    const c = await fingerprint('b.ts', 'const x = 1;')
    expect(a1).toBe(a2)
    expect(a1).not.toBe(b)
    expect(a1).not.toBe(c)
  })

  it('多文件联合指纹', async () => {
    const both = await fingerprint('a.ts\nA', 'b.ts\nB')
    const swapped = await fingerprint('b.ts\nB', 'a.ts\nA')
    expect(both).not.toBe(swapped) // 顺序参与指纹
  })

  it('缩写展示', () => {
    expect(shortFingerprint('sha256:abcdef1234567890')).toBe('sha256:abcdef123456')
    expect(shortFingerprint('plain')).toBe('plain')
  })
})

// ---------- 运行 trace 写入（事件 payload 一并断言） ----------

vi.mock('../api/files', () => ({
  readFile: vi.fn(),
}))
vi.mock('../lib/runner/runFile', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/runner/runFile')>()
  return { ...actual, prepareScript: vi.fn() }
})
vi.mock('../lib/runner/runJavaScript', () => ({
  runJavaScript: vi.fn(),
  runTests: vi.fn(),
}))

const { prepareScript } = await import('../lib/runner/runFile')
const { runJavaScript } = await import('../lib/runner/runJavaScript')
const { runFileInTerminal } = await import('../lib/runner/runToTerminal')
const { useRunStore } = await import('../stores/runStore')

const mockedPrepare = vi.mocked(prepareScript)
const mockedRun = vi.mocked(runJavaScript)

beforeEach(() => {
  vi.clearAllMocks()
  useRunStore.setState({ entries: [], observations: [], running: false, trace: null, activeTab: 'terminal' })
  mockedPrepare.mockResolvedValue({ status: 'ok', code: 'code', transpiled: false })
})

describe('runFileInTerminal 的版本绑定', () => {
  it('运行时写入 trace（traceId/指纹/路径），返回 traceId 供事件关联', async () => {
    mockedRun.mockResolvedValue({ ok: true, durationMs: 5 })
    const result = await runFileInTerminal('src/main.ts', 'console.log(1)')

    expect(result.traceId).toBeTruthy()
    const trace = useRunStore.getState().trace
    expect(trace).not.toBeNull()
    expect(trace!.traceId).toBe(result.traceId)
    expect(trace!.runPath).toBe('src/main.ts')
    expect(trace!.fingerprint).toContain(':') // sha256: 或 fnv1a: 前缀
    expect(trace!.fingerprint).toBe(await fingerprint('src/main.ts', 'console.log(1)'))
  })

  it('再次运行生成新 traceId 与指纹', async () => {
    mockedRun.mockResolvedValue({ ok: true, durationMs: 5 })
    await runFileInTerminal('src/main.ts', 'v1')
    const first = useRunStore.getState().trace!
    await runFileInTerminal('src/main.ts', 'v2')
    const second = useRunStore.getState().trace!
    expect(second.traceId).not.toBe(first.traceId)
    expect(second.fingerprint).not.toBe(first.fingerprint)
  })

  it('不支持的文件类型不写 trace', async () => {
    mockedPrepare.mockResolvedValue({
      status: 'unsupported', code: '', transpiled: false, reason: '不支持 .md',
    })
    const result = await runFileInTerminal('README.md', '# hi')
    expect(result.traceId).toBeNull()
    expect(useRunStore.getState().trace).toBeNull()
  })
})

// ---------- SceneRenderer 过期横幅（§14.3） ----------

const { SceneRenderer } = await import('../viz/SceneRenderer')
const { LATEST_RUN_SCENE } = await import('../viz/scenes')

describe('SceneRenderer trace 头部与过期横幅', () => {
  beforeEach(() => {
    useRunStore.setState({ entries: [], observations: [], running: false, trace: null, activeTab: 'terminal' })
  })

  it('无 trace 时头部不显示运行信息', () => {
    render(<SceneRenderer scene={LATEST_RUN_SCENE} />)
    expect(screen.queryByText(/sha256:|fnv1a:/)).toBeNull()
  })

  it('stale=true 显示过期横幅（不把旧数据冒充当前执行）', () => {
    render(
      <SceneRenderer
        scene={LATEST_RUN_SCENE}
        trace={{
          traceId: 't1',
          fingerprint: 'sha256:abcdef123456',
          runPath: 'src/main.ts',
          at: '2026-10-10T13:00:00Z',
        }}
        stale
      />,
    )
    expect(screen.getByRole('status')).toBeTruthy()
    expect(screen.getByText(/数据已过期/)).toBeTruthy()
    expect(screen.getByText(/旧执行数据/)).toBeTruthy()
  })

  it('stale=false 只显示 trace 头部信息（时间 + 指纹缩写）', () => {
    render(
      <SceneRenderer
        scene={LATEST_RUN_SCENE}
        trace={{
          traceId: 't1',
          fingerprint: 'sha256:abcdef1234567890abcd',
          runPath: 'src/main.ts',
          at: new Date().toISOString(),
        }}
      />,
    )
    expect(screen.getByText(/sha256:abcdef123456/)).toBeTruthy()
    expect(screen.queryByText(/数据已过期/)).toBeNull()
  })

  it('等待异步指纹计算后再渲染不报错', async () => {
    render(<SceneRenderer scene={LATEST_RUN_SCENE} trace={null} />)
    await waitFor(() => expect(screen.getByText('真实执行')).toBeTruthy())
  })
})
