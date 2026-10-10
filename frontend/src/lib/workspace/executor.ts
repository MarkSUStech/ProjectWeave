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

/** 补丁应用结果：由宿主（IdePage）提供，reason 用于精确的用户提示。 */
export interface PatchApplyResult {
  applied: boolean
  /** 未应用的原因（如"目标文件未打开"/"当前有未保存的更改"）。 */
  reason?: string
}

/** A2 确认（针对具体动作）：写入编辑器草稿。
 *
 * 行为与承诺（D28 追记）：应用只改草稿；自动保存随后会把它保存到服务器，
 * 且覆盖前的内容按 D15 进入历史快照——用户代码不丢失。宿主在文件未打开
 * 或存在未保存更改时拒绝应用（保护用户草稿，§10.2 用户内容优先）。
 */
export function confirmPatchAction(
  projectId: string,
  action: WorkspaceAction,
  apply: (path: string, content: string) => PatchApplyResult,
): boolean {
  const path = String(action.payload.path ?? '')
  const content = action.payload.content
  // 队列同步清空（若就是这个待确认动作）
  if (useWorkspaceStore.getState().pendingPatch === action) {
    useWorkspaceStore.getState().setPendingPatch(null)
  }
  if (typeof content !== 'string' || !path) {
    useWorkspaceStore.getState().addNotice(
      'propose-patch',
      `补丁提案只有说明（${String(action.payload.description ?? '')}），没有可应用的内容。`,
      'warn',
    )
    trackClientEvent(
      'workspace-action',
      { kind: 'propose-patch', level: 'A2', outcome: 'rejected', path },
      { projectId },
    )
    return false
  }
  const result = apply(path, content)
  useWorkspaceStore.getState().addNotice(
    'propose-patch',
    result.applied
      ? `已把 AI 补丁写入「${path}」的编辑器草稿；自动保存会将其保存到服务器，应用前的内容已进入历史快照，可随时恢复。`
      : `补丁未应用：${result.reason ?? `目标文件「${path}」当前未打开`}`,
    result.applied ? 'info' : 'warn',
  )
  trackClientEvent(
    'workspace-action',
    { kind: 'propose-patch', level: 'A2', outcome: result.applied ? 'confirmed' : 'rejected', path },
    { projectId },
  )
  return result.applied
}

/** A2 确认（队列中的待确认动作）。 */
export function confirmPendingPatch(
  projectId: string,
  apply: (path: string, content: string) => PatchApplyResult,
): boolean {
  const patch = useWorkspaceStore.getState().pendingPatch
  if (!patch) return false
  return confirmPatchAction(projectId, patch, apply)
}

/** 用户拒绝某个 A2 提案（队列或具体动作通用）。 */
export function dismissPatchAction(projectId: string, action?: WorkspaceAction): void {
  const target = action ?? useWorkspaceStore.getState().pendingPatch
  if (action && useWorkspaceStore.getState().pendingPatch === action) {
    useWorkspaceStore.getState().setPendingPatch(null)
  } else if (!action) {
    useWorkspaceStore.getState().setPendingPatch(null)
  }
  if (target) {
    trackClientEvent(
      'workspace-action',
      { kind: 'propose-patch', level: 'A2', outcome: 'rejected', path: String(target.payload.path ?? '') },
      { projectId },
    )
  }
}
