/**
 * IDE 工作台 UI 状态（工作模式 + 布局锁定），持久化到 localStorage。
 *
 * 布局锁定是设计文档 10.2 的用户控制项：锁定后 setMode 拒绝一切
 * 切换请求（包括未来 AI 的布局建议路径），用户手动解锁后恢复。
 */
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { WorkspaceMode } from '../types/ide'

interface IdeUiState {
  mode: WorkspaceMode
  locked: boolean
  setMode: (mode: WorkspaceMode) => void
  toggleLock: () => void
}

export const useIdeUiStore = create<IdeUiState>()(
  persist(
    (set, get) => ({
      mode: 'coding',
      locked: false,
      setMode: (mode) => {
        if (get().locked) return
        set({ mode })
      },
      toggleLock: () => set((state) => ({ locked: !state.locked })),
    }),
    { name: 'pw-ide-ui' },
  ),
)
