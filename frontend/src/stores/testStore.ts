/**
 * 测试面板状态：最近一次套件运行的结果（按文件聚合）。
 * 不持久化；测试结果的持久化属于学习证据（P2.7），当前仅内存展示。
 */
import { create } from 'zustand'
import type { TestFileResult } from '../types/runner'

interface TestStoreState {
  running: boolean
  /** 文件级进度（done/total）。 */
  progress: { done: number; total: number } | null
  results: TestFileResult[]
  lastRunAt: string | null
  setRunning: (running: boolean) => void
  setProgress: (progress: { done: number; total: number } | null) => void
  resetResults: (total: number) => void
  appendFileResult: (result: TestFileResult) => void
  clear: () => void
}

export const useTestStore = create<TestStoreState>((set) => ({
  running: false,
  progress: null,
  results: [],
  lastRunAt: null,
  setRunning: (running) => set({ running }),
  setProgress: (progress) => set({ progress }),
  resetResults: (total) => set({ results: [], progress: { done: 0, total } }),
  appendFileResult: (result) =>
    set((state) => ({
      results: [...state.results, result],
      progress: state.progress ? { ...state.progress, done: state.progress.done + 1 } : null,
      lastRunAt: new Date().toISOString(),
    })),
  clear: () => set({ results: [], progress: null, lastRunAt: null }),
}))
