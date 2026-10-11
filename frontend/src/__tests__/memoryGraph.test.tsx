/** cpp-memory-graph 组件测试：四态区分、仅已验证关系画箭头、稳定布局、运行态提示。 */

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

// ReactFlow 在 jsdom 需要 resize observer 等 mock（沿用 ConceptGraph 测试的处理方式）
vi.mock('@xyflow/react', async () => {
  const Actual = await vi.importActual<typeof import('@xyflow/react')>('@xyflow/react')
  return {
    ...Actual,
    // jsdom 无真实布局：用轻量替身渲染节点数据，避免 measurement 报错
    ReactFlow: ({ nodes, edges }: { nodes: Array<{ data: unknown }>; edges: Array<{ id: string; source: string; target: string }> }) => (
      <div data-testid="rf-stub">
        {nodes.map((n, i) => <div key={i} data-testid={`node-${i}`}>{JSON.stringify((n as { data: Record<string, unknown> }).data)}</div>)}
        {edges.map((e) => <div key={e.id} data-testid={`edge-${e.id}`}>{`${e.source}->${e.target}`}</div>)}
      </div>
    ),
    Background: () => null,
    Controls: () => null,
  }
})

import { MemoryGraphView } from '../viz/components/memoryGraph'
import { useDebugStore } from '../stores/debugStore'
import type { DebugSnapshot } from '../api/debug'

function snapshot(overrides: Record<string, unknown> = {}) {
  return {
    id: '22222222-0000-4000-8000-000000000001',
    language: 'cpp', status: 'paused', endReason: null, entryPoint: 'src/main.cpp',
    projectId: null, codeFingerprint: null, debuggerProfile: 'lldb-dap:19',
    location: { file: 'src/main.cpp', line: 9, column: 1, frameName: 'main' },
    stopReason: 'breakpoint', pauseSeq: 3, threadId: 1,
    pointerGraph: {
      addresses: { x: '0x0000000000000100', f: '0x0000000000000110' },
      verifiedEdges: [{ from: 'p', to: 'x', address: '0x0000000000000100' }],
      unresolvedPointers: [{ name: 'hp', value: '0x000055555556b2b0' }],
      nullPointers: [{ name: 'np', value: '0x0000000000000000' }],
      evalLimitReached: false,
    },
    threads: [{ id: 1, name: 'app', isPrimary: true }],
    stackFrames: [{ id: 0, name: 'main', file: 'src/main.cpp', line: 9, column: 1 }],
    scopes: [
      {
        name: 'Locals', variablesReference: 1, expensive: false,
        variables: [
          { name: 'x', value: '10', type: 'int', evaluateName: 'x', variablesReference: 0 },
          { name: 'p', value: '0x0000000000000100', type: 'int *', evaluateName: 'p', variablesReference: 4 },
          { name: 'np', value: '0x0000000000000000', type: 'int *', evaluateName: 'np', variablesReference: 5 },
          { name: 'hp', value: '0x000055555556b2b0', type: 'int *', evaluateName: 'hp', variablesReference: 6 },
          { name: 'f', value: '3', type: 'int', evaluateName: 'f', variablesReference: 0 },
        ],
      },
    ],
    breakpoints: [], buildDiagnostics: [], buildStdout: '', error: null, programOutput: [], dapLog: [],
    sandbox: { engine: 'docker', image: null },
    createdAt: '2026-10-11T00:00:00Z', startedAt: null, pausedAt: null, finishedAt: null,
    ...overrides,
  } as DebugSnapshot
}

beforeEach(() => {
  useDebugStore.setState({ snapshot: null, frameVars: {}, selectedFrameId: null, expandedVars: {}, breakpoints: {} })
})

describe('MemoryGraphView', () => {
  it('真实变量值渲染（A）+ 已验证指针关系画箭头（B）+ 未解析/空指针标注（F/G）', () => {
    useDebugStore.setState({ snapshot: snapshot() as never })
    render(<MemoryGraphView instanceId="t" config={{}} />)
    const text = screen.getByTestId('rf-stub').textContent ?? ''
    expect(text).toContain('"value":"10"') // A：真实 x
    // B：唯一箭头 p→x（已验证）
    expect(screen.getByTestId('edge-edge-p-0').textContent).toBe('p->x')
    // F：hp 未解析（不虚构连线——无 hp 的 edge）
    expect(text).toContain('"state":"unresolved"')
    // G：np 空指针状态
    expect(text).toContain('"state":"nullPointer"')
    expect(screen.queryByTestId(/edge-.*hp/)).toBeNull()
    expect(screen.queryByTestId(/edge-.*np/)).toBeNull()
  })

  it('运行中不冒充实时（H）：显示暂停代次历史提示', () => {
    useDebugStore.setState({ snapshot: snapshot({ status: 'running' }) as never })
    render(<MemoryGraphView instanceId="t" config={{}} />)
    expect(screen.getByText(/历史快照，非实时状态/)).toBeTruthy()
  })

  it('无会话/结束显示引导，不渲染图', () => {
    render(<MemoryGraphView instanceId="t" config={{}} />)
    expect(screen.getByText(/启动调试并暂停后/)).toBeTruthy()
  })

  it('指针数据不可用（graph=null）如实标注', () => {
    useDebugStore.setState({
      snapshot: snapshot({ pointerGraph: null }) as never,
    })
    render(<MemoryGraphView instanceId="t" config={{}} />)
    expect(screen.getByText(/指针数据不可用/)).toBeTruthy()
  })

  it('选中帧优先使用帧变量数据', () => {
    useDebugStore.setState({
      snapshot: snapshot() as never,
      selectedFrameId: 7,
      frameVars: {
        7: {
          frameId: 7, pauseSeq: 3,
          scopes: [{
            name: 'Locals', variablesReference: 9, expensive: false,
            variables: [{ name: 'n', value: '2', type: 'int', evaluateName: 'n', variablesReference: 0 }],
          }],
          pointerGraph: null,
        },
      },
    })
    render(<MemoryGraphView instanceId="t" config={{}} />)
    const text = screen.getByTestId('rf-stub').textContent ?? ''
    expect(text).toContain('"value":"2"')
    expect(text).not.toContain('"value":"10"')
  })
})

describe('变化高亮：跨暂停代次 + 递归帧隔离（P5.1 回归）', () => {
  it('同帧值跨代次变化标记 changed；未变化不标记', () => {
    const base = {
      scopes: [{
        name: 'Locals', variablesReference: 1, expensive: false,
        variables: [
          { name: 'x', value: '10', type: 'int', evaluateName: 'x', variablesReference: 0 },
          { name: 'y', value: '5', type: 'int', evaluateName: 'y', variablesReference: 0 },
        ],
      }],
      pointerGraph: null,
    }
    // 第一次暂停（代次 1）：无历史，无变化标记
    useDebugStore.setState({ snapshot: snapshot({ pauseSeq: 1, ...base }) as never, selectedFrameId: null })
    const { unmount } = render(<MemoryGraphView instanceId="t" config={{}} />)
    let text = screen.getByTestId('rf-stub').textContent ?? ''
    expect(text).toContain('"changed":false')
    unmount()

    // 第二次暂停（代次 2）：x 变为 20 → changed:true；y 不变 → false
    useDebugStore.setState({
      snapshot: snapshot({
        pauseSeq: 2,
        scopes: [{
          name: 'Locals', variablesReference: 1, expensive: false,
          variables: [
            { name: 'x', value: '20', type: 'int', evaluateName: 'x', variablesReference: 0 },
            { name: 'y', value: '5', type: 'int', evaluateName: 'y', variablesReference: 0 },
          ],
        }],
        pointerGraph: null,
      }) as never,
    })
    render(<MemoryGraphView instanceId="t" config={{}} />)
    text = screen.getByTestId('rf-stub').textContent ?? ''
    expect(text).toContain('"value":"20"')
    const xNode = text.split('{"label":"x"')[1]?.split('}')[0] ?? ''
    expect(xNode).toContain('"changed":true')
    const yNode = text.split('{"label":"y"')[1]?.split('}')[0] ?? ''
    expect(yNode).toContain('"changed":false')
  })

  it('递归帧隔离：帧 7 的同名变量 x 不与顶帧历史比较', () => {
    // 顶帧历史：x=10（上一渲染遗留或先渲染顶帧）
    useDebugStore.setState({
      snapshot: snapshot({
        pauseSeq: 1,
        scopes: [{
          name: 'Locals', variablesReference: 1, expensive: false,
          variables: [{ name: 'x', value: '10', type: 'int', evaluateName: 'x', variablesReference: 0 }],
        }],
        pointerGraph: null,
      }) as never,
      selectedFrameId: null,
    })
    const { unmount } = render(<MemoryGraphView instanceId="t" config={{}} />)
    unmount()

    // 切到帧 7：其 x 值 999（与顶帧 10 不同），但帧 7 无自身历史 → 不标 changed
    useDebugStore.setState({
      selectedFrameId: 7,
      frameVars: {
        7: {
          frameId: 7, pauseSeq: 1,
          scopes: [{
            name: 'Locals', variablesReference: 9, expensive: false,
            variables: [{ name: 'x', value: '999', type: 'int', evaluateName: 'x', variablesReference: 0 }],
          }],
          pointerGraph: null,
        },
      },
    })
    render(<MemoryGraphView instanceId="t" config={{}} />)
    const text = screen.getByTestId('rf-stub').textContent ?? ''
    const xNode = text.split('{"label":"x"')[1]?.split('}')[0] ?? ''
    expect(xNode).toContain('"changed":false')
  })
})
