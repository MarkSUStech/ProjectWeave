import { useState } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Button } from '../components/ui/Button'
import { PanelTabs } from '../components/ui/PanelTabs'
import { Dialog, DialogTrigger, DialogContent, DialogTitle, DialogDescription } from '../components/ui/upstream/dialog'
import { CommandPalette } from '../components/ide/CommandPalette'
import { useIdeUiStore } from '../stores/ideUiStore'
import { conceptEdges } from '../lib/conceptGraph'
import { terminalLine } from '../lib/terminal'
import type { Concept } from '../types/concept'
import { useReducedMotion } from 'motion/react'
import { BlurFade } from '../components/ui/upstream/blur-fade'
import { AnimatedGroup } from '../components/ui/upstream/animated-group'
import { releaseDiffModels } from '../lib/diffLifecycle'

vi.mock('motion/react', async (importOriginal) => ({ ...(await importOriginal<typeof import('motion/react')>()), useReducedMotion: vi.fn(() => false) }))

beforeEach(() => { useIdeUiStore.setState({ mode: 'coding', locked: false }); vi.mocked(useReducedMotion).mockReturnValue(false) })

describe('组件基础的真实交互', () => {
  it('减少动态效果时卡片无模糊/位移，消息组不隐藏内容', () => {
    vi.mocked(useReducedMotion).mockReturnValue(true)
    const { container } = render(<><BlurFade><p>项目</p></BlurFade><AnimatedGroup preset="blur-slide"><p>教学消息</p></AnimatedGroup></>)
    expect(container.firstElementChild?.getAttribute('style')).toContain('opacity: 1')
    expect(container.querySelector('[style*="blur"]')).toBeNull()
    expect(container.querySelector('[style*="translate"]')).toBeNull()
    expect(container.querySelector('[style*="opacity: 0"]')).toBeNull()
  })
  it('Button asChild 保留链接语义，disabled 阻止执行', async () => {
    const click = vi.fn()
    render(<><Button asChild><a href="/concepts">打开图谱</a></Button><Button disabled onClick={click}>保存</Button></>)
    expect(screen.getByRole('link', { name: '打开图谱' }).getAttribute('href')).toBe('/concepts')
    await userEvent.setup().click(screen.getByRole('button', { name: '保存' }))
    expect(click).not.toHaveBeenCalled()
  })
  it('Radix 页签用方向键切换，关联真实面板', async () => {
    function Fixture() {
      const [tab, setTab] = useState('files')
      return <PanelTabs value={tab} onChange={setTab} items={[{ id: 'files', label: '文件' }, { id: 'history', label: '历史' }]} label="资源">{tab === 'files' ? '文件内容' : '快照内容'}</PanelTabs>
    }
    render(<Fixture />)
    const user = userEvent.setup()
    await user.click(screen.getByRole('tab', { name: '文件' }))
    await user.keyboard('{ArrowRight}')
    await waitFor(() => expect(screen.getByRole('tab', { name: '历史' }).getAttribute('aria-selected')).toBe('true'))
    const panel = screen.getByRole('tabpanel')
    expect(panel.textContent).toBe('快照内容')
    expect(screen.getByRole('tab', { name: '历史' }).getAttribute('aria-controls')).toBe(panel.id)
  })
  it('对话框有名称，Escape 关闭并恢复触发器焦点', async () => {
    render(<Dialog><DialogTrigger asChild><Button>重命名</Button></DialogTrigger><DialogContent><DialogTitle>文件路径</DialogTitle><DialogDescription>输入新的路径</DialogDescription><input aria-label="路径" /></DialogContent></Dialog>)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: '重命名' }))
    expect(screen.getByRole('dialog', { name: '文件路径' })).toBeTruthy()
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(document.activeElement).toBe(screen.getByRole('button', { name: '重命名' }))
  })
  it('命令面板搜索真实文件并打开，锁定时模式命令禁用', async () => {
    useIdeUiStore.setState({ locked: true })
    const openFile = vi.fn()
    render(<CommandPalette files={[{ path: 'src/main.ts', size: 12, updatedAt: '2026-10-10T00:00:00Z' }]} onOpenFile={openFile} onSave={vi.fn()} onRun={vi.fn()} canSave={false} canRun={false} />)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: '打开命令面板' }))
    expect(screen.getByRole('option', { name: '切换到调试模式' }).getAttribute('aria-disabled')).toBe('true')
    await user.type(screen.getByPlaceholderText('搜索文件或命令…'), 'main.ts')
    await user.click(screen.getByRole('option', { name: 'src/main.ts' }))
    expect(openFile).toHaveBeenCalledWith('src/main.ts')
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})

describe('真实数据到专业组件的适配', () => {
  it('关闭差异视图先解除绑定再释放两个模型，重复清理不泄漏或重复释放', () => {
    let attached = true
    const dispose = vi.fn(() => { if (attached) throw new Error('仍有 Diff widget 引用') })
    const owner = { getModel: () => attached ? { original: { dispose }, modified: { dispose } } : null, setModel: () => { attached = false } }
    releaseDiffModels(owner)
    releaseDiffModels(owner)
    expect(dispose).toHaveBeenCalledTimes(2)
  })
  it('图的连线只来自存在的先修关系，不造缺失节点', () => {
    const concepts = [{ id: 'base', prerequisites: [] }, { id: 'next', prerequisites: ['base', 'missing'] }] as unknown as Concept[]
    expect(conceptEdges(concepts)).toEqual([{ id: 'base->next', source: 'base', target: 'next' }])
  })
  it('终端保留输出换行与颜色，清除用户输出中的控制序列', () => {
    const result = terminalLine({ id: 1, at: '2026-10-10T00:00:00Z', kind: 'error', text: 'first\nsecond\x1b[2J\x07' })
    expect(result).toContain('\x1b[91mfirst\r\nsecond[2J')
    expect(result).not.toContain('\x1b[2J')
    expect(result).not.toContain('\x07')
  })
})
