/** 工作台动作执行器测试（§10.2/AT-05）：分级执行、锁定联防、撤销、A2 确认、事件。 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { TutorDecision, WorkspaceAction } from '../types/tutor'

vi.mock('../api/events', () => ({
  ingestEvents: vi.fn().mockResolvedValue({ accepted: 1, duplicated: 0 }),
}))
vi.mock('../lib/eventTracker', () => ({
  trackClientEvent: vi.fn(),
}))

const { trackClientEvent } = await import('../lib/eventTracker')
const mockedTrack = vi.mocked(trackClientEvent)
const { useIdeUiStore } = await import('../stores/ideUiStore')
const { useWorkspaceStore } = await import('../stores/workspaceStore')
const {
  applyWorkspaceActions,
  confirmPendingPatch,
  dismissPendingPatch,
  undoLastLayoutChange,
} = await import('../lib/workspace/executor')
const { WorkspaceNoticeStrip } = await import('../components/ide/WorkspaceNoticeStrip')

function decision(actions: WorkspaceAction[]): TutorDecision {
  return {
    id: '6e2d6f6e-1b1f-4c0f-9b8a-2f2f5c6a7b8d',
    projectId: 'p1',
    question: 'q',
    trigger: 'user',
    intent: 'hint',
    hintLevel: 2,
    message: 'm',
    targetConcepts: [],
    explanation: 'e',
    confidence: 0.6,
    outcome: 'accepted',
    outcomeReason: '',
    workspaceActions: actions,
    policyVersion: 'gate-v1',
    promptTokens: 1,
    completionTokens: 1,
    model: 'mock',
    createdAt: 't',
  }
}

const notice = (message: string): WorkspaceAction => ({
  kind: 'display-notice', level: 'A0', reason: 'r', payload: { message },
})
const switchLayout = (mode: string): WorkspaceAction => ({
  kind: 'switch-layout', level: 'A1', reason: '排查需要', payload: { mode },
})
const patch = (path = 'src/main.ts', content?: string): WorkspaceAction => ({
  kind: 'propose-patch', level: 'A2', reason: '用户要求答案',
  payload: { path, description: '完整实现', ...(content !== undefined ? { content } : {}) },
})

beforeEach(() => {
  vi.clearAllMocks()
  useIdeUiStore.setState({ mode: 'coding', locked: false })
  useWorkspaceStore.setState({ notices: [], undoStack: [], pendingPatch: null })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('applyWorkspaceActions', () => {
  it('A0 通知立即执行并上报 executed', () => {
    applyWorkspaceActions(decision([notice('看第 3 行')]), 'p1')
    const state = useWorkspaceStore.getState()
    expect(state.notices).toHaveLength(1)
    expect(state.notices[0].text).toBe('看第 3 行')
    expect(mockedTrack).toHaveBeenCalledWith(
      'workspace-action',
      expect.objectContaining({ kind: 'display-notice', level: 'A0', outcome: 'executed' }),
      { projectId: 'p1' },
    )
  })

  it('A1 未锁定：切换布局 + 撤销栈 + executed；撤销恢复原模式', () => {
    applyWorkspaceActions(decision([switchLayout('debugging')]), 'p1')
    expect(useIdeUiStore.getState().mode).toBe('debugging')
    expect(useWorkspaceStore.getState().undoStack).toHaveLength(1)

    undoLastLayoutChange('p1')
    expect(useIdeUiStore.getState().mode).toBe('coding') // 恢复
    expect(useWorkspaceStore.getState().undoStack).toHaveLength(0)
  })

  it('A1 锁定（AT-05）：拒绝切换、显示原因、上报 rejected、不进撤销栈', () => {
    useIdeUiStore.setState({ locked: true })
    applyWorkspaceActions(decision([switchLayout('debugging')]), 'p1')
    expect(useIdeUiStore.getState().mode).toBe('coding') // 未变
    expect(useWorkspaceStore.getState().undoStack).toHaveLength(0)
    const noticeState = useWorkspaceStore.getState().notices[0]
    expect(noticeState.tone).toBe('warn')
    expect(noticeState.text).toContain('布局已锁定')
    expect(mockedTrack).toHaveBeenCalledWith(
      'workspace-action',
      expect.objectContaining({ kind: 'switch-layout', outcome: 'rejected' }),
      { projectId: 'p1' },
    )
  })

  it('撤销本身也尊重锁定', () => {
    applyWorkspaceActions(decision([switchLayout('debugging')]), 'p1')
    useIdeUiStore.setState({ locked: true })
    undoLastLayoutChange('p1')
    expect(useIdeUiStore.getState().mode).toBe('debugging') // 撤销被拒绝，保持
    expect(useWorkspaceStore.getState().notices.at(-1)?.text).toContain('撤销被拒绝')
  })

  it('A2：进入确认队列（不执行），上报 needs-confirmation', () => {
    applyWorkspaceActions(decision([patch()]), 'p1')
    expect(useWorkspaceStore.getState().pendingPatch?.kind).toBe('propose-patch')
    expect(mockedTrack).toHaveBeenCalledWith(
      'workspace-action',
      expect.objectContaining({ kind: 'propose-patch', outcome: 'needs-confirmation' }),
      { projectId: 'p1' },
    )
  })
})

describe('A2 确认流程', () => {
  it('确认后写入草稿（经宿主回调），上报 confirmed', () => {
    applyWorkspaceActions(decision([patch('src/main.ts', 'new content')]), 'p1')
    const apply = vi.fn().mockReturnValue(true)
    const ok = confirmPendingPatch('p1', apply)
    expect(ok).toBe(true)
    expect(apply).toHaveBeenCalledWith('src/main.ts', 'new content')
    expect(useWorkspaceStore.getState().pendingPatch).toBeNull()
    expect(mockedTrack).toHaveBeenCalledWith(
      'workspace-action',
      expect.objectContaining({ kind: 'propose-patch', outcome: 'confirmed' }),
      { projectId: 'p1' },
    )
  })

  it('目标文件未打开：apply 返回 false → 提示并上报 rejected', () => {
    applyWorkspaceActions(decision([patch('src/other.ts', 'x')]), 'p1')
    const ok = confirmPendingPatch('p1', () => false)
    expect(ok).toBe(false)
    expect(useWorkspaceStore.getState().notices.at(-1)?.text).toContain('未打开')
    expect(mockedTrack).toHaveBeenCalledWith(
      'workspace-action',
      expect.objectContaining({ outcome: 'rejected' }),
      { projectId: 'p1' },
    )
  })

  it('拒绝：清空队列并上报 rejected', () => {
    applyWorkspaceActions(decision([patch()]), 'p1')
    dismissPendingPatch('p1')
    expect(useWorkspaceStore.getState().pendingPatch).toBeNull()
    expect(mockedTrack).toHaveBeenCalledWith(
      'workspace-action',
      expect.objectContaining({ kind: 'propose-patch', outcome: 'rejected' }),
      { projectId: 'p1' },
    )
  })
})

describe('WorkspaceNoticeStrip（UI 集成点组件）', () => {
  it('A0 通知显示、可关闭；A2 确认卡可应用', async () => {
    applyWorkspaceActions(decision([notice('提示内容'), patch('a.ts', 'content')]), 'p1')
    const apply = vi.fn().mockReturnValue(true)
    render(<WorkspaceNoticeStrip projectId="p1" onApplyPatch={apply} />)

    expect(screen.getByText('提示内容')).toBeTruthy()
    expect(screen.getByRole('alertdialog')).toBeTruthy()

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: '应用到编辑器草稿' }))
    expect(apply).toHaveBeenCalledWith('a.ts', 'content')

    await user.click(screen.getAllByRole('button', { name: '关闭' })[0])
    expect(screen.queryByText('提示内容')).toBeNull()
  })

  it('A1 切换后显示撤销按钮；空状态不渲染', async () => {
    const { container, rerender } = render(
      <WorkspaceNoticeStrip projectId="p1" onApplyPatch={() => false} />,
    )
    expect(container.firstChild).toBeNull() // 无通知无提案 → 不渲染

    applyWorkspaceActions(decision([switchLayout('debugging')]), 'p1')
    rerender(<WorkspaceNoticeStrip projectId="p1" onApplyPatch={() => false} />)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /撤销 AI 布局切换/ }))
    expect(useIdeUiStore.getState().mode).toBe('coding')
  })
})
