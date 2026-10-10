/**
 * 调试工作台状态（P4.5a）：
 * - 断点集合（path → 行号列表，Monaco glyph margin 点击维护）；
 * - 当前调试会话快照（轮询刷新；全部来自真实 LLDB DAP 数据）；
 * - 调试指令与懒加载变量缓存。
 * 不持久化（断点随项目文件恢复属后续课程绑定阶段）。
 */

import { create } from 'zustand'
import {
  expandDebugVariables,
  getDebugSnapshot,
  sendDebugCommand,
  startDebugSession,
  stopDebugSession,
  type DebugBreakpointInput,
  type DebugCommand,
  type DebugSnapshot,
  type DebugVariable,
} from '../api/debug'
import { ApiError } from '../api/client'

const POLL_INTERVAL_MS = 700
const TERMINAL = new Set(['terminated'])

interface DebugStoreState {
  /** 断点：项目相对路径 → 升序行号。 */
  breakpoints: Record<string, number[]>
  /** 当前会话（null = 未在调试）。 */
  snapshot: DebugSnapshot | null
  starting: boolean
  commanding: boolean
  error: string | null
  /** 懒加载变量缓存：variablesReference → 子变量。 */
  expandedVars: Record<number, DebugVariable[]>
  toggleBreakpoint: (path: string, line: number) => void
  hasBreakpoints: () => boolean
  toBreakpointInputs: () => DebugBreakpointInput[]
  start: (input: {
    entryPoint: string
    files: Record<string, string>
    codeFingerprint?: string
    projectId?: string
    stopOnEntry?: boolean
  }) => Promise<void>
  command: (cmd: DebugCommand) => Promise<void>
  stop: () => Promise<void>
  expandVar: (variablesReference: number) => Promise<void>
  dismissError: () => void
}

let pollTimer: ReturnType<typeof setInterval> | null = null

function stopPolling() {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

export const useDebugStore = create<DebugStoreState>((set, get) => ({
  breakpoints: {},
  snapshot: null,
  starting: false,
  commanding: false,
  error: null,
  expandedVars: {},

  toggleBreakpoint: (path, line) => {
    set((state) => {
      const lines = state.breakpoints[path] ?? []
      const next = lines.includes(line)
        ? lines.filter((l) => l !== line)
        : [...lines, line].sort((a, b) => a - b)
      const breakpoints = { ...state.breakpoints }
      if (next.length === 0) delete breakpoints[path]
      else breakpoints[path] = next
      return { breakpoints }
    })
    // 会话进行中：断点变化同步到调试器（整文件替换语义）
    const { snapshot } = get()
    if (snapshot && snapshot.status !== 'terminated') {
      void get().command('setBreakpoints')
    }
  },

  hasBreakpoints: () => Object.keys(get().breakpoints).length > 0,

  toBreakpointInputs: () =>
    Object.entries(get().breakpoints).map(([path, lines]) => ({ path, lines })),

  start: async (input) => {
    const state = get()
    if (state.starting || state.snapshot?.status !== 'terminated' && state.snapshot !== null) {
      // 已有活动会话：拒绝并发启动
      if (state.snapshot && state.snapshot.status !== 'terminated') return
    }
    const bps = state.toBreakpointInputs()
    if (bps.length === 0) {
      set({ error: '请先在行号区域点击设置至少一个断点（C++ 调试需要断点或选择入口暂停）' })
      return
    }
    set({ starting: true, error: null, snapshot: null, expandedVars: {} })
    try {
      const created = await startDebugSession({
        entryPoint: input.entryPoint,
        files: input.files,
        breakpoints: bps,
        stopOnEntry: input.stopOnEntry ?? false,
        codeFingerprint: input.codeFingerprint,
        projectId: input.projectId,
      })
      const snap = await getDebugSnapshot(created.id)
      set({ snapshot: snap, starting: false })
      stopPolling()
      pollTimer = setInterval(() => {
        void pollOnce(created.id, set)
      }, POLL_INTERVAL_MS)
    } catch (err) {
      set({
        starting: false,
        error: err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err),
      })
    }
  },

  command: async (cmd) => {
    const { snapshot } = get()
    if (!snapshot || snapshot.status === 'terminated') return
    set({ commanding: true, error: null })
    try {
      const next = cmd === 'setBreakpoints'
        ? await sendDebugCommand(snapshot.id, cmd, { breakpoints: get().toBreakpointInputs() })
        : await sendDebugCommand(snapshot.id, cmd)
      set({ snapshot: next, commanding: false })
      if (next.status === 'terminated') stopPolling()
    } catch (err) {
      set({
        commanding: false,
        error: err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err),
      })
    }
  },

  stop: async () => {
    const { snapshot } = get()
    stopPolling()
    if (!snapshot) return
    if (snapshot.status === 'terminated') return
    try {
      const final = await stopDebugSession(snapshot.id)
      set({ snapshot: final })
    } catch {
      // 停止失败不阻塞 UI；轮询终态会收敛
    }
  },

  expandVar: async (variablesReference) => {
    const { snapshot, expandedVars } = get()
    if (!snapshot || variablesReference in expandedVars) return
    try {
      const { variables } = await expandDebugVariables(snapshot.id, variablesReference)
      set({ expandedVars: { ...expandedVars, [variablesReference]: variables } })
    } catch {
      // 懒加载失败静默（面板显示无子项）
    }
  },

  dismissError: () => set({ error: null }),
}))

async function pollOnce(id: string, set: (partial: Partial<DebugStoreState>) => void) {
  try {
    const snap = await getDebugSnapshot(id)
    const current = useDebugStore.getState().snapshot
    // 会话已被替换（新会话启动）时放弃旧轮询
    if (!current || current.id !== id) {
      stopPolling()
      return
    }
    set({ snapshot: snap })
    if (TERMINAL.has(snap.status)) stopPolling()
  } catch {
    // 网络闪断容忍：下轮重试
  }
}
