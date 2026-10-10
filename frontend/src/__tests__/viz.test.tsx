/** Visual Interaction Engine 地基测试：场景 schema、注册表、渲染器、时间线组件。 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { teachingSceneSchema, type TeachingScene } from '../viz/sceneSchema'
import { clearRegistryForTests, getComponent, listComponents, registerComponent } from '../viz/registry'
import { ensureBuiltinComponents } from '../viz/builtinComponents'
import { SceneRenderer } from '../viz/SceneRenderer'
import { useRunStore } from '../stores/runStore'
import { LATEST_RUN_SCENE } from '../viz/scenes'

const validScene: TeachingScene = {
  sceneId: 's1',
  templateId: 'runtime.console-timeline.v1',
  objectiveId: null,
  sourceType: 'runtime',
  dataBinding: { ref: 'run:latest' },
  components: [{ id: 'c1', type: 'console-timeline', config: {} }],
  allowedInteractions: ['step'],
}

describe('TeachingScene schema', () => {
  it('解析合法场景并应用默认值', () => {
    const parsed = teachingSceneSchema.parse({
      sceneId: 's', templateId: 't.v1', sourceType: 'conceptual',
      components: [{ id: 'a', type: 'x' }],
    })
    expect(parsed.allowedInteractions).toEqual([])
    expect(parsed.objectiveId).toBeNull()
    expect(parsed.components[0].config).toEqual({})
  })

  it('拒绝非法来源与空组件', () => {
    expect(() =>
      teachingSceneSchema.parse({ ...validScene, sourceType: 'dream' }),
    ).toThrow()
    expect(() => teachingSceneSchema.parse({ ...validScene, components: [] })).toThrow()
  })
})

describe('组件注册表', () => {
  beforeEach(() => {
    clearRegistryForTests()
    ensureBuiltinComponents()
  })

  it('内置 console-timeline 已注册且元数据完整', () => {
    const meta = getComponent('console-timeline')
    expect(meta).toBeDefined()
    expect(meta!.dataSources).toContain('run:latest')
    expect(meta!.supportedConcepts.length).toBeGreaterThan(0)
    expect(listComponents().length).toBeGreaterThanOrEqual(1)
  })

  it('重复注册抛错', () => {
    expect(() =>
      registerComponent({
        componentId: 'console-timeline',
        version: 'v1',
        supportedConcepts: [],
        dataSources: [],
        renderCapabilities: [],
        accessibilityDescription: '',
        View: () => null,
      }),
    ).toThrow(/重复注册/)
  })
})

describe('SceneRenderer', () => {
  beforeEach(() => {
    clearRegistryForTests()
    ensureBuiltinComponents()
    useRunStore.setState({ entries: [], running: false, activeTab: 'terminal' })
  })

  it('渲染来源标签"真实执行"与运行输出时间线', () => {
    useRunStore.setState({
      entries: [
        { id: 1, kind: 'log', text: '第一条输出', at: '2026-10-10T13:00:00Z' },
        { id: 2, kind: 'error', text: '出错啦', at: '2026-10-10T13:00:01Z' },
        { id: 3, kind: 'system', text: '▶ 运行（应被过滤）', at: '2026-10-10T13:00:02Z' },
      ],
    })
    render(<SceneRenderer scene={validScene} />)
    expect(screen.getByText('真实执行')).toBeTruthy()
    expect(screen.getByText(/第一条输出/)).toBeTruthy()
    expect(screen.getByText(/出错啦/)).toBeTruthy()
    expect(screen.queryByText(/应被过滤/)).toBeNull()
    expect(screen.getByText('+0000ms')).toBeTruthy()
    expect(screen.getByText('+1000ms')).toBeTruthy()
  })

  it('无运行数据时显示诚实空态', () => {
    render(<SceneRenderer scene={validScene} />)
    expect(screen.getByText(/还没有运行输出/)).toBeTruthy()
  })

  it('点击条目展开详情（本地交互，无 LLM）', async () => {
    useRunStore.setState({
      entries: [{ id: 1, kind: 'log', text: 'hello', at: '2026-10-10T13:00:00Z' }],
    })
    render(<SceneRenderer scene={validScene} />)
    const user = userEvent.setup()
    await user.click(screen.getByText(/hello/))
    expect(screen.getByText(/级别：log/)).toBeTruthy()
    expect(screen.getByText(/条目 #1/)).toBeTruthy()
  })

  it('未注册组件显式报错，不伪装渲染', () => {
    render(<SceneRenderer scene={{ ...validScene, components: [{ id: 'x', type: 'magic-3d', config: {} }] }} />)
    expect(screen.getByRole('alert')).toBeTruthy()
    expect(screen.getByText(/未注册的可视化组件：magic-3d/)).toBeTruthy()
  })

  it('schema 不合法的场景显式报错', () => {
    render(<SceneRenderer scene={{ bad: 'scene' }} />)
    expect(screen.getByText('场景描述不合法')).toBeTruthy()
  })

  it('内置标准场景可渲染', () => {
    render(<SceneRenderer scene={LATEST_RUN_SCENE} />)
    expect(screen.getByText('runtime.console-timeline.v1')).toBeTruthy()
    expect(screen.getByText('真实执行')).toBeTruthy()
  })
})
