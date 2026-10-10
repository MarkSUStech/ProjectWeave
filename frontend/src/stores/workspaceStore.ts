/**
 * 工作台动作状态（§10.2）：A0 通知、A1 布局撤销栈、A2 补丁确认队列。
 * 不持久化（会话级 UI 状态）。
 */
import { create } from 'zustand'
import type { WorkspaceAction } from '../types/tutor'

export interface WorkspaceNotice {
  id: number
  tone: 'info' | 'warn'
  /** 动作 kind 或 'undo'（用户撤销反馈）。 */
  source: string
  text: string
}

export interface LayoutUndoEntry {
  token: string
  previousMode: string
}

interface WorkspaceStoreState {
  notices: WorkspaceNotice[]
  undoStack: LayoutUndoEntry[]
  pendingPatch: WorkspaceAction | null
  addNotice: (source: string, text: string, tone?: 'info' | 'warn') => void
  dismissNotice: (id: number) => void
  pushUndo: (token: string, previousMode: string) => void
  popUndo: () => LayoutUndoEntry | null
  setPendingPatch: (action: WorkspaceAction | null) => void
}

let nextNoticeId = 1
const MAX_NOTICES = 4
const MAX_UNDO = 10

export const useWorkspaceStore = create<WorkspaceStoreState>((set) => ({
  notices: [],
  undoStack: [],
  pendingPatch: null,
  addNotice: (source, text, tone = 'info') =>
    set((state) => {
      const notice: WorkspaceNotice = { id: nextNoticeId++, tone, source, text }
      const notices = [...state.notices, notice]
      return { notices: notices.slice(-MAX_NOTICES) }
    }),
  dismissNotice: (id) =>
    set((state) => ({ notices: state.notices.filter((n) => n.id !== id) })),
  pushUndo: (token, previousMode) =>
    set((state) => ({ undoStack: [...state.undoStack, { token, previousMode }].slice(-MAX_UNDO) })),
  // 实现内自引用 getState 会造成类型循环推断，故显式注解返回类型
  popUndo: (): LayoutUndoEntry | null => {
    const stack = useWorkspaceStore.getState().undoStack
    const entry = stack.length > 0 ? stack[stack.length - 1] : null
    if (entry) {
      set((state) => ({ undoStack: state.undoStack.slice(0, -1) }))
    }
    return entry
  },
  setPendingPatch: (pendingPatch) => set({ pendingPatch }),
}))
