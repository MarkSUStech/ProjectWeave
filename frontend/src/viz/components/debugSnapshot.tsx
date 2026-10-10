/**
 * L1 标准组件：真实调试快照（debug snapshot，P4.5a）。
 *
 * 数据绑定 debug:latest —— 渲染当前 LLDB 会话的真实暂停数据：
 * 当前执行位置、调用栈、局部变量（含变化次数对比），全部来自
 * Docker 沙箱内 lldb-dap 的 DAP 响应（非 AI 推测）。
 * 本地交互（选中栈帧）零 LLM。
 */
import { useMemo } from 'react'
import { useDebugStore } from '../../stores/debugStore'

interface VarSeen {
  value: string
  changes: number
}

/** 帧内变化历史：键 = 帧:代次（隔离递归同名变量与代次，D38）。 */
const frameSeen = new Map<string, Map<string, VarSeen>>()

export function DebugSnapshotView({ config }: { instanceId: string; config: Record<string, unknown> }) {
  const snapshot = useDebugStore((s) => s.snapshot)
  const selectedFrameId = useDebugStore((s) => s.selectedFrameId)
  const selectFrame = useDebugStore((s) => s.selectFrame)
  const maxFrames = typeof config.maxFrames === 'number' ? config.maxFrames : 8
  const selectedFrame = selectedFrameId ?? 0

  // 变量变化追踪：同一次会话内对比前后暂停的值（仅对顶帧 Locals）
  const locals = useMemo(() => {
    const scope = snapshot?.scopes.find((s) => s.name === 'Locals')
    return scope?.variables ?? []
  }, [snapshot?.scopes])
  // 变化历史键 = 帧:暂停代次（换帧/新暂停即隔离；递归同名变量不串扰——D38）
  const historyRef = useMemo(() => new Map<string, VarSeen>(), [snapshot?.id])
  const varRows = useMemo(() => {
    const rows: Array<{ name: string; value: string; changed: boolean; changes: number }> = []
    const seenKey = `f${selectedFrame}:p${snapshot?.pauseSeq ?? 0}`
    let seen = frameSeen.get(seenKey)
    if (!seen) {
      frameSeen.clear() // 只保留当前帧+代次
      seen = new Map()
      frameSeen.set(seenKey, seen)
    }
    for (const v of locals) {
      const prev = seen.get(v.name)
      const changes = prev ? (prev.value === v.value ? prev.changes : prev.changes + 1) : 0
      seen.set(v.name, { value: v.value, changes })
      rows.push({ name: v.name, value: v.value, changed: prev !== undefined && prev.value !== v.value, changes })
    }
    return rows
  }, [locals, historyRef, selectedFrame, snapshot?.pauseSeq])

  if (!snapshot || snapshot.status === 'terminated') {
    return (
      <div className="flex h-full items-center justify-center p-4 text-center text-xs leading-relaxed text-ink-faint">
        {snapshot?.endReason
          ? `调试会话已结束（${snapshot.endReason}）。设置断点并启动调试后，这里展示真实 LLDB 数据。`
          : '启动 LLDB 调试并暂停后，这里展示真实执行位置、调用栈与变量状态（来自 Docker 沙箱内的调试器，非 AI 推测）。'}
      </div>
    )
  }

  const loc = snapshot.location
  const frames = snapshot.stackFrames.slice(0, maxFrames)
  const activeFrame = frames[Math.min(selectedFrame, frames.length - 1)]

  return (
    <div className="flex h-full min-h-0 flex-col gap-2 overflow-y-auto p-3 text-xs">
      <div className="flex shrink-0 items-center justify-between">
        <span className="text-[10px] uppercase tracking-wide text-ink-faint">
          runtime · debug:latest — 真实 {snapshot.debuggerProfile} 会话
        </span>
        {snapshot.status === 'paused' && loc && (
          <span className="font-mono text-warn">▶ {loc.frameName} @ {loc.file}:{loc.line}</span>
        )}
      </div>

      {/* 1. 当前执行位置 */}
      <section className="rounded border border-edge-soft bg-panel px-2.5 py-2">
        <div className="mb-1 text-[10px] font-medium text-ink-faint">当前执行位置（暂停原因：{snapshot.stopReason ?? snapshot.status}）</div>
        {loc ? (
          <div className="font-mono text-[11px]">
            <span className="text-warn">{loc.file}:{loc.line}</span>
            <span className="ml-2 text-ink-dim">函数 {loc.frameName}</span>
          </div>
        ) : (
          <div className="text-[11px] text-ink-faint">程序运行中（{snapshot.status}）…</div>
        )}
      </section>

      <div className="grid min-h-0 flex-1 grid-cols-2 gap-2">
        {/* 2. 调用栈（可选中帧） */}
        <section className="min-h-0 overflow-y-auto rounded border border-edge-soft bg-panel px-2.5 py-2">
          <div className="mb-1 text-[10px] font-medium text-ink-faint">调用栈（{snapshot.stackFrames.length} 帧，点击选中）</div>
          {frames.length === 0 && <div className="text-[11px] text-ink-faint">（暂停后显示）</div>}
          <ul className="space-y-0.5">
            {frames.map((frame, i) => (
              <li key={frame.id}>
                <button
                  type="button"
                  onClick={() => selectFrame(frame.id)}
                  className={`flex w-full items-baseline gap-1.5 rounded px-1 py-0.5 text-left font-mono text-[10px] ${
                    i === Math.min(selectedFrame, frames.length - 1) ? 'bg-accent-soft text-ink' : 'text-ink-dim hover:bg-panel-2'
                  }`}
                >
                  <span className="w-4 text-right text-ink-faint">{i}</span>
                  <span className="truncate">{frame.name}</span>
                  {frame.file && <span className="ml-auto shrink-0 text-ink-faint">{frame.file}:{frame.line}</span>}
                </button>
              </li>
            ))}
          </ul>
          {activeFrame && (
            <div className="mt-1 border-t border-edge-soft pt-1 text-[10px] text-ink-faint">
              选中帧：{activeFrame.name}（{activeFrame.file ?? '?'}:{activeFrame.line ?? '?'}）
            </div>
          )}
        </section>

        {/* 3. 变量值与变化（顶帧） */}
        <section className="min-h-0 overflow-y-auto rounded border border-edge-soft bg-panel px-2.5 py-2">
          <div className="mb-1 text-[10px] font-medium text-ink-faint">局部变量（真实值 · 变化标记）</div>
          {varRows.length === 0 && <div className="text-[11px] text-ink-faint">（暂停后显示）</div>}
          <ul className="space-y-0.5 font-mono text-[10px]">
            {varRows.map((row) => (
              <li key={row.name} className="flex items-baseline gap-2 px-1">
                <span className="shrink-0 text-ink-faint">{row.name}</span>
                <span className={`truncate ${row.changed ? 'text-accent' : 'text-ink'}`}>
                  {row.value}
                </span>
                {row.changes > 0 && (
                  <span className="ml-auto shrink-0 text-[9px] text-accent">↻{row.changes}</span>
                )}
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  )
}
