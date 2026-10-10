/**
 * 工作台动作通知条（§10.2）：A0 通知 / A1 拒绝原因 / 撤销入口 / A2 补丁确认卡。
 * 自包含组件——宿主（IdePage/MentorPanel）挂载即可，不依赖外部 props。
 */
import { useWorkspaceStore } from '../../stores/workspaceStore'
import {
  confirmPendingPatch,
  dismissPendingPatch,
  undoLastLayoutChange,
} from '../../lib/workspace/executor'

export function WorkspaceNoticeStrip({
  projectId,
  onApplyPatch,
}: {
  projectId: string
  /** 返回是否应用成功（由宿主提供：仅当目标文件已打开时写入草稿）。 */
  onApplyPatch: (path: string, content: string) => boolean
}) {
  const notices = useWorkspaceStore((state) => state.notices)
  const dismiss = useWorkspaceStore((state) => state.dismissNotice)
  const undoStack = useWorkspaceStore((state) => state.undoStack)
  const pendingPatch = useWorkspaceStore((state) => state.pendingPatch)

  if (notices.length === 0 && pendingPatch === null) {
    return null
  }

  return (
    <div className="shrink-0 border-b border-edge-soft">
      {notices.map((notice) => (
        <div
          key={notice.id}
          role="status"
          className={`flex items-center justify-between gap-3 px-3 py-1.5 text-[11px] ${
            notice.tone === 'warn'
              ? 'bg-warn/10 text-warn'
              : 'bg-accent-soft/60 text-ink-dim'
          }`}
        >
          <span className="min-w-0">
            <span className="mr-2 rounded bg-panel-2 px-1.5 py-0.5 text-[10px]">
              AI · {notice.source}
            </span>
            {notice.text}
          </span>
          <button
            type="button"
            onClick={() => dismiss(notice.id)}
            className="shrink-0 rounded px-1.5 py-0.5 text-ink-faint hover:text-ink"
          >
            关闭
          </button>
        </div>
      ))}

      {undoStack.length > 0 && (
        <div className="flex items-center justify-end border-t border-edge-soft/60 px-3 py-1">
          <button
            type="button"
            onClick={() => undoLastLayoutChange(projectId)}
            className="rounded border border-edge px-2 py-0.5 text-[11px] text-ink-dim hover:border-accent/50 hover:text-ink"
          >
            ↩ 撤销 AI 布局切换
          </button>
        </div>
      )}

      {pendingPatch !== null && (
        <div
          role="alertdialog"
          aria-label="AI 补丁提案确认"
          className="space-y-2 border-t border-warn/30 bg-warn/5 px-3 py-2 text-xs"
        >
          <div className="font-medium text-warn">
            A2 · AI 补丁提案（需确认才会应用，应用后仅写入草稿、不自动保存）
          </div>
          <div className="text-ink-dim">
            文件：<span className="font-mono">{String(pendingPatch.payload.path ?? '')}</span>
          </div>
          <div className="text-ink-dim">
            说明：{String(pendingPatch.payload.description ?? '')}
          </div>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => dismissPendingPatch(projectId)}
              className="rounded border border-edge px-2.5 py-1 text-[11px] text-ink-dim hover:text-ink"
            >
              拒绝
            </button>
            <button
              type="button"
              onClick={() => confirmPendingPatch(projectId, onApplyPatch)}
              className="rounded bg-warn/90 px-2.5 py-1 text-[11px] font-medium text-white hover:bg-warn"
            >
              应用到编辑器草稿
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
