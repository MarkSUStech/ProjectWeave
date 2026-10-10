/**
 * 终端面板状态：运行输出条目、运行中标记、面板页签。
 * 不持久化（运行输出是易失信息）。
 */
import { create } from 'zustand'
import type { ConsoleLevel, TerminalEntry } from '../types/runner'

export type BottomTab = 'terminal' | 'tests' | 'events'

/** 终端最多保留的条目数，防止长会话内存膨胀。 */
const MAX_ENTRIES = 500

let nextEntryId = 1

interface RunStoreState {
  entries: TerminalEntry[]
  running: boolean
  activeTab: BottomTab
  appendEntry: (kind: 'system' | ConsoleLevel, text: string) => void
  setRunning: (running: boolean) => void
  setActiveTab: (tab: BottomTab) => void
  clear: () => void
}

export const useRunStore = create<RunStoreState>((set) => ({
  entries: [],
  running: false,
  activeTab: 'terminal',
  appendEntry: (kind, text) =>
    set((state) => {
      const entry: TerminalEntry = { id: nextEntryId++, kind, text, at: new Date().toISOString() }
      const entries = [...state.entries, entry]
      return { entries: entries.length > MAX_ENTRIES ? entries.slice(-MAX_ENTRIES) : entries }
    }),
  setRunning: (running) => set({ running }),
  setActiveTab: (activeTab) => set({ activeTab }),
  clear: () => set({ entries: [] }),
}))
