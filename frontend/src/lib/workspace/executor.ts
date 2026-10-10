/**
 * 工作台动作执行器（§10.2 权限等级 / §13.3 校验链的执行段）：
 * - A0 display-notice：直接显示可关闭通知；
 * - A1 switch-layout：**尊重布局锁定**——锁定时拒绝并显示原因（AT-05），
 *   未锁定时切换布局并压入撤销栈（撤销同样受锁定约束，见 IdePage）；
 * - A2 propose-patch：不直接执行，进入确认队列（展示参数，用户确认后
 *   才写入编辑器草稿，且不会自动保存）。
 * 每个动作的执行结果上报 workspace-action 事件（审计）。
 */
import type { TutorDecision, WorkspaceAction } from '../../types/tutor'
import type { WorkspaceMode } from '../../types/ide'
import { useWorkspaceStore } from '../../stores/workspaceStore'
import { useIdeUiStore } from '../../stores/ideUiStore'
import { trackClientEvent } from '../eventTracker'

function report(projectId: string, decision: TutorDecision, action: WorkspaceAction, outcome: string) {
  trackClientEvent(
    'workspace-action',
    {
      kind: action.kind,
      level: action.level,
      outcome,
      decisionId: decision.id,
      reason: action.reason.slice(0, 120),
    },
    { projectId },
  )
}

export function applyWorkspaceActions(decision: TutorDecision, projectId: string): void {
  const workspace = useWorkspaceStore.getState()
  const ide = useIdeUiStore.getState()

  for (const [index, action] of decision.workspaceActions.entries()) {
    if (action.kind === 'display-notice') {
      const message = String(action.payload.message ?? '')
      if (message) {
        workspace.addNotice('display-notice', message)
        report(projectId, decision, action, 'executed')
      }
      continue
    }

    if (action.kind === 'switch-layout') {
      const mode = action.payload.mode as WorkspaceMode
      if (ide.locked) {
        // AT-05：用户锁定布局后 AI 的切换动作被拒绝并记录原因
        workspace.addNotice(
          'switch-layout',
          `已拒绝 AI 的布局切换建议（${mode}）：布局已锁定。${action.reason}`,
          'warn',
        )
        report(projectId, decision, action, 'rejected')
        continue
      }
      workspace.pushUndo(`${decision.id}:${index}`, ide.mode)
      ide.setMode(mode)
      workspace.addNotice('switch-layout', `AI 已切换布局到「${mode}」（可撤销）`)
      report(projectId, decision, action, 'executed')
      continue
    }

    if (action.kind === 'propose-patch') {
      // A2：不执行，进入确认队列（用户看到参数与说明后决定）
      useWorkspaceStore.getState().setPendingPatch(action)
      report(projectId, decision, action, 'needs-confirmation')
    }
  }
}

/** 用户撤销最近一次 AI 布局切换（同样尊重锁定）。 */
export function undoLastLayoutChange(projectId: string): void {
  const workspace = useWorkspaceStore.getState()
  const ide = useIdeUiStore.getState()
  if (ide.locked) {
    workspace.addNotice('undo', '撤销被拒绝：布局已锁定。', 'warn')
    trackClientEvent(
      'workspace-action',
      { kind: 'switch-layout', level: 'A1', outcome: 'undo-rejected' },
      { projectId },
    )
    return
  }
  const entry = useWorkspaceStore.getState().popUndo()
  if (entry === null) {
    return
  }
  useIdeUiStore.getState().setMode(entry.previousMode as WorkspaceMode)
  useWorkspaceStore.getState().addNotice('undo', `已撤销布局切换，回到「${entry.previousMode}」`)
  trackClientEvent(
    'workspace-action',
    { kind: 'switch-layout', level: 'A1', outcome: 'undone', token: entry.token },
    { projectId },
  )
}

/** A2 确认：把补丁内容写入编辑器草稿（不保存）；返回是否应用成功。 */
export function confirmPendingPatch(
  projectId: string,
  apply: (path: string, content: string) => boolean,
): boolean {
  const patch = useWorkspaceStore.getState().pendingPatch
  useWorkspaceStore.getState().setPendingPatch(null)
  if (!patch) return false
  const path = String(patch.payload.path ?? '')
  const content = patch.payload.content
  if (typeof content !== 'string' || !path) {
    useWorkspaceStore.getState().addNotice(
      'propose-patch',
      `补丁提案只有说明（${String(patch.payload.description ?? '')}），没有可应用的内容。`,
      'warn',
    )
    return false
  }
  const applied = apply(path, content)
  useWorkspaceStore.getState().addNotice(
    'propose-patch',
    applied
      ? `已把 AI 补丁写入「${path}」的编辑器草稿（未保存，请检查后自行保存）。`
      : `补丁目标文件「${path}」当前未打开，请先打开该文件再应用。`,
    applied ? 'info' : 'warn',
  )
  trackClientEvent(
    'workspace-action',
    { kind: 'propose-patch', level: 'A2', outcome: applied ? 'confirmed' : 'rejected', path },
    { projectId },
  )
  return applied
}

/** 用户拒绝 A2 提案。 */
export function dismissPendingPatch(projectId: string): void {
  const patch = useWorkspaceStore.getState().pendingPatch
  useWorkspaceStore.getState().setPendingPatch(null)
  if (patch) {
    trackClientEvent(
      'workspace-action',
      { kind: 'propose-patch', level: 'A2', outcome: 'rejected', path: String(patch.payload.path ?? '') },
      { projectId },
    )
  }
}
