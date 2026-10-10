/**
 * 终端面板状态：运行输出条目、变量观察序列、运行中标记、面板页签。
 * 不持久化（运行输出是易失信息）。
 */
import { create } from 'zustand'
import type { ConsoleLevel, Observation, TerminalEntry } from '../types/runner'

export type BottomTab = 'terminal' | 'tests' | 'events'

/** 终端最多保留的条目数，防止长会话内存膨胀。 */
const MAX_ENTRIES = 500
/** 变量观察序列上限（每个变量保留最近 N 次变化由组件截断）。 */
const MAX_OBSERVATIONS = 200

let nextEntryId = 1
let nextObservationId = 1

/** 最近一次运行的追踪信息（§14.3：画布数据与被执行代码的版本绑定）。 */
export interface RunTrace {
  traceId: string
  /** 被执行内容的指纹（SHA-256(path\0content)，多文件用 \n 连接）。 */
  fingerprint: string
  runPath: string | null
  at: string
}

interface RunStoreState {
  entries: TerminalEntry[]
  observations: Observation[]
  running: boolean
  trace: RunTrace | null
  activeTab: BottomTab
  appendEntry: (kind: 'system' | ConsoleLevel, text: string) => void
  appendObservation: (name: string, value: string) => void
  setRunning: (running: boolean) => void
  setTrace: (trace: RunTrace) => void
  setActiveTab: (tab: BottomTab) => void
  clear: () => void
}

export const useRunStore = create<RunStoreState>((set) => ({
  entries: [],
  observations: [],
  running: false,
  trace: null,
  activeTab: 'terminal',
  appendEntry: (kind, text) =>
    set((state) => {
      const entry: TerminalEntry = { id: nextEntryId++, kind, text, at: new Date().toISOString() }
      const entries = [...state.entries, entry]
      return { entries: entries.length > MAX_ENTRIES ? entries.slice(-MAX_ENTRIES) : entries }
    }),
  appendObservation: (name, value) =>
    set((state) => {
      const observation: Observation = {
        id: nextObservationId++,
        name,
        value,
        at: new Date().toISOString(),
      }
      const observations = [...state.observations, observation]
      return {
        observations:
          observations.length > MAX_OBSERVATIONS
            ? observations.slice(-MAX_OBSERVATIONS)
            : observations,
      }
    }),
  setRunning: (running) => set({ running }),
  setTrace: (trace) => set({ trace }),
  setActiveTab: (activeTab) => set({ activeTab }),
  clear: () => set({ entries: [], observations: [], trace: null }),
}))
