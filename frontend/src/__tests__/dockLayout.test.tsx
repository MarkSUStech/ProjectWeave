import { useState, type ReactNode } from 'react'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { dockLayoutKey, readDockLayout, validateDockLayout, WORKSPACE_PANELS, writeDockLayout, type WorkspacePanelId } from '../lib/dockLayout'
import { WorkspaceLayout } from '../components/ide/WorkspaceLayout'
import { WorkspaceLayoutProvider, useWorkspaceLayout } from '../components/ide/WorkspaceLayoutContext'
import { WorkspaceViewMenu } from '../components/ide/WorkspaceViewMenu'
import { useIdeUiStore } from '../stores/ideUiStore'
import { Orientation, type SerializedDockview } from 'dockview-react'
import { SettingsButton } from '../components/settings/SettingsButton'
import { useAppearanceStore } from '../stores/appearanceStore'

beforeEach(() => {
  localStorage.clear()
  useIdeUiStore.setState({ mode: 'coding', locked: false })
  useAppearanceStore.setState({ open: false })
})

function StatefulPanel({ id }: { id: WorkspacePanelId }) {
  const [draft, setDraft] = useState('')
  return <input aria-label={`${id}草稿`} value={draft} onChange={(event) => setDraft(event.target.value)} />
}
function Harness() {
  const controls = useWorkspaceLayout()
  const mode = useIdeUiStore((s) => s.mode)
  return <>
    <WorkspaceViewMenu />
    <SettingsButton />
    <button onClick={() => controls?.hide('mentor')}>测试隐藏</button>
    <button onClick={() => controls?.reveal('mentor')}>测试显示</button>
    <button onClick={() => controls?.move('mentor', 'left')}>测试移动</button>
    <button onClick={() => controls?.move('mentor', 'within', 'files')}>测试合并</button>
    <button onClick={() => controls?.float('mentor')}>测试悬浮</button>
    <button onClick={() => controls?.reset()}>测试重置</button>
    <button onClick={() => WORKSPACE_PANELS.forEach(({ id }) => controls?.hide(id))}>测试全隐藏</button>
    <output data-testid="visible">{controls?.visible.join(',')}</output>
    <div style={{ width: 1200, height: 800 }}><WorkspaceLayout mode={mode} projectId="project-a"
      panels={Object.fromEntries(WORKSPACE_PANELS.map(({ id }) => [id, <StatefulPanel key={id} id={id} />])) as Record<WorkspacePanelId, ReactNode>} /></div>
  </>
}
const mount = () => render(<WorkspaceLayoutProvider><Harness /></WorkspaceLayoutProvider>)
const saved = () => readDockLayout(localStorage, 'project-a', useIdeUiStore.getState().mode)

describe('自由布局的实际组件与持久化', () => {
  it('设置里的显隐连接真实面板，锁定禁用开关，恢复外观不改变布局', async () => {
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByRole('button', { name: '打开界面设置' }))
    await user.click(screen.getByRole('tab', { name: '工作区布局' }))
    await user.click(screen.getByRole('switch', { name: '显示AI 导师' }))
    await waitFor(() => expect(saved()?.panels.mentor).toBeUndefined())
    await user.click(screen.getByRole('switch', { name: '锁定布局' }))
    expect((screen.getByRole('switch', { name: '显示编辑器' }) as HTMLButtonElement).disabled).toBe(true)
    await user.click(screen.getByRole('button', { name: '恢复默认外观' }))
    expect(saved()?.panels.mentor).toBeUndefined()
    expect(useIdeUiStore.getState().locked).toBe(true)
    await user.click(screen.getByRole('switch', { name: '锁定布局' }))
    await user.click(screen.getByRole('switch', { name: '显示AI 导师' }))
    await waitFor(() => expect(saved()?.panels.mentor).toBeDefined())
  })
  it('移动、合并、隐藏与恢复不卸载面板草稿，刷新恢复可见状态', async () => {
    const user = userEvent.setup()
    const view = mount()
    await user.type(await screen.findByLabelText('mentor草稿'), '还未发送的内容')
    await user.click(screen.getByText('测试移动'))
    await waitFor(() => expect(JSON.stringify(saved()?.grid.root)).toMatch(/"views":\["mentor"\].*"views":\["files"/))
    await user.click(screen.getByText('测试合并'))
    expect(screen.getByLabelText('mentor草稿').getAttribute('value')).toBe('还未发送的内容')
    await user.click(screen.getByText('测试隐藏'))
    await waitFor(() => expect(screen.getByTestId('visible').textContent).not.toContain('mentor'))
    await waitFor(() => expect(saved()?.panels.mentor).toBeUndefined())
    await user.click(screen.getByText('测试显示'))
    expect(screen.getByLabelText('mentor草稿').getAttribute('value')).toBe('还未发送的内容')
    await user.click(screen.getByText('测试隐藏'))
    await waitFor(() => expect(saved()?.panels.mentor).toBeUndefined())
    view.unmount()
    mount()
    await waitFor(() => expect(screen.getByTestId('visible').textContent).not.toContain('mentor'))
  })

  it('项目/模式布局独立，重置恢复默认；全部隐藏仍能通过视图入口恢复', async () => {
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByText('测试隐藏'))
    await waitFor(() => expect(saved()?.panels.mentor).toBeUndefined())
    act(() => useIdeUiStore.getState().setMode('debugging'))
    await waitFor(() => expect(screen.getByTestId('visible').textContent).toContain('mentor'))
    expect(screen.getByTestId('visible').textContent).toContain('canvas')
    act(() => useIdeUiStore.getState().setMode('coding'))
    await waitFor(() => expect(screen.getByTestId('visible').textContent).not.toContain('mentor'))
    expect(readDockLayout(localStorage, 'project-b', 'coding')).toBeNull()
    await user.click(screen.getByText('测试重置'))
    await waitFor(() => expect(screen.getByTestId('visible').textContent).toContain('mentor'))
    await user.click(screen.getByText('测试全隐藏'))
    await screen.findByText('所有面板已隐藏')
    await user.click(screen.getByRole('button', { name: '视图与面板' }))
    await user.click(screen.getByRole('menuitemcheckbox', { name: '编辑器' }))
    await waitFor(() => expect(screen.getByTestId('visible').textContent).toBe('editor'))
  })

  it('锁定拒绝关闭/移动/悬浮/重置，菜单禁用；解锁后可悬浮并保存', async () => {
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByText('测试移动'))
    await waitFor(() => expect(saved()).not.toBeNull())
    const before = JSON.stringify(saved()?.grid)
    act(() => useIdeUiStore.getState().toggleLock())
    for (const title of ['测试隐藏', '测试移动', '测试悬浮', '测试重置']) await user.click(screen.getByText(title))
    expect(JSON.stringify(saved()?.grid)).toBe(before)
    expect(screen.getByTestId('visible').textContent).toContain('mentor')
    await user.click(screen.getByRole('button', { name: '视图与面板' }))
    expect(screen.getByRole('menuitemcheckbox', { name: 'AI 导师' }).getAttribute('data-disabled')).not.toBeNull()
    await user.keyboard('{Escape}')
    act(() => useIdeUiStore.getState().toggleLock())
    await user.click(screen.getByText('测试悬浮'))
    await waitFor(() => expect(saved()?.floatingGroups?.length).toBe(1))
    expect((screen.getByRole('button', { name: '专注AI 导师' }) as HTMLButtonElement).disabled).toBe(true)
    await user.click(screen.getByRole('button', { name: '视图与面板' }))
    expect(screen.getByRole('menuitem', { name: '专注当前面板' }).getAttribute('data-disabled')).not.toBeNull()
  })

  it('损坏存储回退到可用预设并显式提示', async () => {
    localStorage.setItem(dockLayoutKey('project-a', 'coding'), '{bad json')
    mount()
    expect((await screen.findByText(/已保存的布局无法恢复/)).closest('[role="alert"]')).not.toBeNull()
    expect(screen.getByTestId('visible').textContent).toContain('editor')
  })
})

describe('布局存储边界', () => {
  const layout: SerializedDockview = { grid: { root: { type: 'leaf', data: { id: 'g1', views: ['editor'], activeView: 'editor' } }, width: 1200, height: 800, orientation: Orientation.HORIZONTAL },
    panels: { editor: { id: 'editor', contentComponent: 'workspace' } } }
  it('只接受注册面板，拒绝重复引用、非有限尺寸和弹出窗口', () => {
    expect(validateDockLayout(layout)).toBe(true)
    expect(validateDockLayout({ ...layout, panels: { unknown: { id: 'unknown', contentComponent: 'workspace' } } })).toBe(false)
    expect(validateDockLayout({ ...layout, grid: { ...layout.grid, width: Infinity } })).toBe(false)
    expect(validateDockLayout({ ...layout, grid: { ...layout.grid, root: { type: 'leaf', data: { id: 'g1', views: ['editor', 'editor'] } } } })).toBe(false)
    expect(validateDockLayout({ ...layout, popoutGroups: [{ url: 'https://example.com' }] })).toBe(false)
  })
  it('存储写后可读，恢复时剥离任意参数并恢复真实标题与组件', () => {
    writeDockLayout(localStorage, 'p', 'coding', { ...layout, panels: { editor: { ...layout.panels.editor, title: '任意标题', params: { draft: '禁止持久化业务草稿' } } } })
    const restored = readDockLayout(localStorage, 'p', 'coding')
    expect(restored?.panels.editor.title).toBe('编辑器')
    expect(restored?.panels.editor.params).toBeUndefined()
    expect(restored?.panels.editor.renderer).toBe('always')
    expect(localStorage.getItem(dockLayoutKey('p', 'coding'))).not.toContain('禁止持久化业务草稿')
  })
})
