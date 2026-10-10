import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { APPEARANCE_KEY, DEFAULT_APPEARANCE, useAppearanceStore, appearanceSchema } from '../stores/appearanceStore'
import { AppearanceProvider } from '../components/settings/AppearanceProvider'
import { SettingsButton } from '../components/settings/SettingsButton'
import { EditorPanel } from '../components/ide/EditorPanel'
import { AppShell } from '../components/AppShell'
import { appearanceVariables, contrastRatio, readableAccent, THEME_PALETTES } from '../lib/appearance'
import { useIdeUiStore } from '../stores/ideUiStore'
import { BlurFade } from '../components/ui/upstream/blur-fade'
import { useUiReducedMotion } from '../hooks/useUiReducedMotion'

vi.mock('../lib/monaco', () => ({ configureMonaco: vi.fn() }))
vi.mock('@monaco-editor/react', () => ({ default: ({ options, value }: { options: object; value: string }) => <><output data-testid="editor-options">{JSON.stringify(options)}</output><output data-testid="editor-content">{value}</output></> }))
beforeEach(() => {
  localStorage.clear()
  useAppearanceStore.setState({ preferences: { ...DEFAULT_APPEARANCE }, open: false, error: null, hydrated: false })
  useIdeUiStore.setState({ mode: 'coding', locked: false })
  document.documentElement.removeAttribute('style')
})

describe('外观设置的真实存储边界', () => {
  it('更新写后可读；刷新恢复外观且不恢复弹窗状态', () => {
    useAppearanceStore.getState().update({ theme: 'paper', accent: '#80c7ef', editorFontSize: 18 })
    useAppearanceStore.setState({ preferences: { ...DEFAULT_APPEARANCE }, hydrated: false, open: false })
    useAppearanceStore.getState().hydrate()
    expect(useAppearanceStore.getState().preferences).toMatchObject({ theme: 'paper', accent: '#80c7ef', editorFontSize: 18 })
    expect(useAppearanceStore.getState().open).toBe(false)
    expect(JSON.parse(localStorage.getItem(APPEARANCE_KEY)!).preferences).not.toHaveProperty('open')
  })
  it('损坏/版本不兼容存储回退并显式报错，新增字段有默认值', () => {
    for (const raw of ['{broken', JSON.stringify({ version: 2, preferences: {} }), JSON.stringify({ version: 1, preferences: { accent: 'url(evil)' } })]) {
      localStorage.setItem(APPEARANCE_KEY, raw)
      useAppearanceStore.setState({ hydrated: false })
      useAppearanceStore.getState().hydrate()
      expect(useAppearanceStore.getState().preferences).toEqual(DEFAULT_APPEARANCE)
      expect(useAppearanceStore.getState().error).toContain('无法读取')
    }
    expect(appearanceSchema.parse({ theme: 'midnight' }).editorFontSize).toBe(14)
  })
  it('拒绝范围外数值和颜色注入；剥离未定义字段', () => {
    const before = useAppearanceStore.getState().preferences
    useAppearanceStore.getState().update({ editorFontSize: 200, accent: 'red;display:none' })
    expect(useAppearanceStore.getState().preferences).toBe(before)
    expect(useAppearanceStore.getState().error).toContain('无效')
    expect(appearanceSchema.parse({ secret: 'not part of preferences' })).not.toHaveProperty('secret')
  })
  it('存储不可写时设置仍生效并提示，恢复外观不重置布局锁定', () => {
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota') })
    useAppearanceStore.getState().update({ density: 'compact' })
    expect(useAppearanceStore.getState().preferences.density).toBe('compact')
    expect(useAppearanceStore.getState().error).toContain('未能保存')
    spy.mockRestore()
    useIdeUiStore.setState({ locked: true })
    useAppearanceStore.getState().reset()
    expect(useAppearanceStore.getState().preferences).toEqual(DEFAULT_APPEARANCE)
    expect(useIdeUiStore.getState().locked).toBe(true)
  })
  it('极端强调色在三种表面上保持文字对比，按钮填色保留原色', () => {
    for (const c of Object.values(THEME_PALETTES)) for (const accent of ['#ffffff', '#000000', '#c1b5ff', '#888888']) {
      expect(contrastRatio(readableAccent(accent, c.panel), c.panel)).toBeGreaterThanOrEqual(4.5)
    }
    expect(appearanceVariables({ ...DEFAULT_APPEARANCE, theme: 'paper', accent: '#c1b5ff' })['--color-primary']).toBe('#c1b5ff')
  })
})

describe('设置入口与真实控件', () => {
  it('设置打开时组合键不会保存或运行背后的文件，关闭后恢复', () => {
    const onSave = vi.fn(), onRun = vi.fn()
    render(<EditorPanel openPath="src/main.ts" content="const a = 1" dirty saving={false} error={null} lastSavedAt={null} running={false} onChange={vi.fn()} onSave={onSave} onRun={onRun} />)
    act(() => useAppearanceStore.getState().setOpen(true))
    fireEvent.keyDown(window, { key: 's', ctrlKey: true })
    fireEvent.keyDown(window, { key: 'Enter', ctrlKey: true })
    expect(onSave).not.toHaveBeenCalled()
    expect(onRun).not.toHaveBeenCalled()
    act(() => useAppearanceStore.getState().setOpen(false))
    fireEvent.keyDown(window, { key: 's', ctrlKey: true })
    fireEvent.keyDown(window, { key: 'Enter', ctrlKey: true })
    expect(onSave).toHaveBeenCalledOnce()
    expect(onRun).toHaveBeenCalledOnce()
  })
  it('全站入口打开，键盘切换主题，即时应用/保存并返回入口焦点', async () => {
    const user = userEvent.setup()
    render(<AppearanceProvider><MemoryRouter><AppShell><p>真实页面</p></AppShell></MemoryRouter></AppearanceProvider>)
    const button = screen.getByRole('button', { name: '打开界面设置' })
    await user.click(button)
    expect(screen.getByRole('dialog', { name: '界面设置' })).not.toBeNull()
    act(() => screen.getByRole('radio', { name: '石墨灰' }).focus())
    // Radix 异步移动焦点，jsdom 需让按键状态持续到焦点完成。
    await user.keyboard('{ArrowRight>}')
    await waitFor(() => expect(useAppearanceStore.getState().preferences.theme).toBe('midnight'))
    await user.keyboard('{/ArrowRight}')
    expect(document.documentElement.dataset.uiTheme).toBe('midnight')
    await user.click(screen.getByRole('button', { name: '强调色：天蓝' }))
    expect(document.documentElement.style.getPropertyValue('--color-primary')).toBe('#80c7ef')
    const colorInput = screen.getByRole('textbox', { name: '强调色十六进制值' })
    await user.clear(colorInput)
    await user.type(colorInput, '#ad89ff')
    expect(document.documentElement.style.getPropertyValue('--color-primary')).toBe('#ad89ff')
    await user.clear(colorInput)
    await user.type(colorInput, '#bad')
    await user.tab()
    expect((colorInput as HTMLInputElement).value).toBe('#ad89ff')
    expect(useAppearanceStore.getState().preferences.accent).toBe('#ad89ff')
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(document.activeElement).toBe(button)
  })
  it('编辑器选项实时更新，内容保持；样式、密度和圆角同步应用', async () => {
    const user = userEvent.setup()
    render(<AppearanceProvider><SettingsButton /><EditorPanel openPath="src/main.ts" content="未保存代码" dirty saving={false} error={null} lastSavedAt={null} running={false} onChange={vi.fn()} onSave={vi.fn()} onRun={vi.fn()} /></AppearanceProvider>)
    await user.click(screen.getByRole('button', { name: '打开界面设置' }))
    await user.click(screen.getByRole('radio', { name: '紧凑' }))
    fireEvent.change(screen.getByRole('slider', { name: '圆角大小' }), { target: { value: '0' } })
    expect(document.documentElement.style.getPropertyValue('--radius-lg')).toBe('0px')
    expect(document.documentElement.style.getPropertyValue('--pw-tab-height')).toBe('30px')
    await user.click(screen.getByRole('tab', { name: '编辑器与终端' }))
    fireEvent.change(screen.getByRole('slider', { name: '代码字号' }), { target: { value: '18' } })
    await user.click(screen.getByRole('switch', { name: '自动换行' }))
    await user.click(screen.getByRole('switch', { name: '显示行号' }))
    await user.click(screen.getByRole('switch', { name: '显示代码缩略图' }))
    await user.keyboard('{Escape}')
    expect(JSON.parse(screen.getByTestId('editor-options').textContent!)).toMatchObject({ fontSize: 18, wordWrap: 'on', lineNumbers: 'off', minimap: { enabled: true } })
    expect(screen.getByTestId('editor-content').textContent).toBe('未保存代码')
  })
  it('关闭动效同时关闭 JS 模糊/位移并标记 CSS，设置错误可见', async () => {
    function ReducedState() { return <output data-testid="reduced">{String(useUiReducedMotion())}</output> }
    render(<AppearanceProvider><ReducedState /><BlurFade><p>项目卡片</p></BlurFade><SettingsButton /></AppearanceProvider>)
    act(() => useAppearanceStore.getState().update({ motion: false }))
    expect(screen.getByTestId('reduced').textContent).toBe('true')
    expect(document.documentElement.dataset.uiMotion).toBe('off')
    await waitFor(() => expect(screen.getByText('项目卡片').parentElement?.getAttribute('style')).not.toContain('blur'))
    act(() => { useAppearanceStore.setState({ error: '存储失败', open: true }) })
    expect(await screen.findByRole('alert')).not.toBeNull()
  })
  it('从命令或全站打开同一设置；无工作区时如实显示入口说明', async () => {
    render(<AppearanceProvider><SettingsButton /></AppearanceProvider>)
    act(() => useAppearanceStore.getState().setOpen(true))
    await userEvent.setup().click(screen.getByRole('tab', { name: '工作区布局' }))
    await waitFor(() => expect(screen.getByText(/进入项目的教学工作区后/)).not.toBeNull())
    expect(screen.queryByRole('switch', { name: '显示编辑器' })).toBeNull()
  })
})
