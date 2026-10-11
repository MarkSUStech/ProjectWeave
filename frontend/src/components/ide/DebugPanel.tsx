/**
 * 调试面板（P4.5a）：调用栈 / 作用域变量 / 线程。
 * 数据全部来自真实 LLDB DAP 会话快照（debugStore 轮询），非推测；
 * 复杂对象按 variablesReference 懒加载展开。
 */
import { useDebugStore } from '../../stores/debugStore'
import type { DebugVariable } from '../../api/debug'
import { PlaceholderState } from '../ui/PlaceholderState'

const STATUS_LABELS: Record<string, { text: string; tone: string }> = {
  creating: { text: '创建中', tone: 'text-ink-faint' },
  building: { text: '编译中（-O0 -g）', tone: 'text-warn' },
  configuring: { text: '启动调试器', tone: 'text-warn' },
  running: { text: '运行中', tone: 'text-accent' },
  paused: { text: '已暂停', tone: 'text-warn' },
  terminated: { text: '已结束', tone: 'text-ink-faint' },
}

const END_REASON_LABELS: Record<string, string> = {
  completed: '程序正常结束',
  'build-failed': '编译失败（调试器未启动）',
  'debugger-error': '调试器错误',
  timeout: '会话超时回收',
  cancelled: '已停止',
  'internal-error': '内部错误',
}

function ValueVariable({ variable, depth }: { variable: DebugVariable; depth: number }) {
  const expandedVars = useDebugStore((s) => s.expandedVars)
  const expandVar = useDebugStore((s) => s.expandVar)
  const hasChildren = variable.variablesReference > 0
  const children = hasChildren ? expandedVars[variable.variablesReference] : undefined
  const open = children !== undefined

  return (
    <div>
      <button
        type="button"
        disabled={!hasChildren}
        onClick={() => void expandVar(variable.variablesReference)}
        className="flex w-full items-baseline gap-2 rounded px-1.5 py-0.5 text-left font-mono text-[11px] hover:bg-panel-2 disabled:cursor-default"
        style={{ paddingLeft: `${6 + depth * 14}px` }}
      >
        <span className="w-3 shrink-0 text-ink-faint">{hasChildren ? (open ? '▾' : '▸') : '·'}</span>
        <span className="shrink-0 text-ink">{variable.name}</span>
        <span className="truncate text-accent">{variable.value}</span>
        {variable.type && <span className="ml-auto shrink-0 text-[10px] text-ink-faint">{variable.type}</span>}
      </button>
      {open && children.map((child) => (
        <ValueVariable key={child.name} variable={child} depth={depth + 1} />
      ))}
    </div>
  )
}

export function DebugPanel({ onOpenFile }: { onOpenFile?: (path: string) => void }) {
  const snapshot = useDebugStore((s) => s.snapshot)
  const error = useDebugStore((s) => s.error)
  const dismissError = useDebugStore((s) => s.dismissError)
  const frameVars = useDebugStore((s) => s.frameVars)
  const selectedFrameId = useDebugStore((s) => s.selectedFrameId)
  const selectFrame = useDebugStore((s) => s.selectFrame)

  // 选中帧的作用域数据（未加载时回落顶帧快照，并触发按帧重载）
  const activeScopes = selectedFrameId !== null && frameVars[selectedFrameId]
    ? frameVars[selectedFrameId].scopes
    : snapshot?.scopes ?? []

  if (!snapshot && !error) {
    return (
      <PlaceholderState
        title="调试面板"
        description="在 C++ 文件的行号区域点击设置断点，然后点击编辑器工具栏的「调试」启动 LLDB 会话。暂停后这里显示真实的调用栈、线程与局部变量（来自 Docker 沙箱内的 lldb-dap）。"
      />
    )
  }

  const status = snapshot ? STATUS_LABELS[snapshot.status] ?? { text: snapshot.status, tone: 'text-ink-faint' } : null

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center justify-between border-b border-edge-soft px-3 py-1">
        <span className="text-[11px] text-ink-faint">
          LLDB 调试 · {snapshot?.debuggerProfile ?? 'lldb-dap'}
          {status && <span className={`ml-2 ${status.tone}`}>● {status.text}</span>}
          {snapshot?.status === 'paused' && snapshot.location && (
            <span className="ml-2 font-mono text-warn">
              {snapshot.location.file}:{snapshot.location.line}
            </span>
          )}
          {snapshot?.status === 'terminated' && snapshot.endReason && (
            <span className="ml-2 text-ink-faint">（{END_REASON_LABELS[snapshot.endReason] ?? snapshot.endReason}）</span>
          )}
        </span>
        <span className="text-[10px] text-ink-faint">数据来自真实调试会话</span>
      </div>

      {error && (
        <div role="alert" className="flex items-start justify-between gap-2 border-b border-danger/30 bg-danger/10 px-3 py-1.5 text-xs text-danger">
          <span className="whitespace-pre-wrap">{error}</span>
          <button type="button" onClick={dismissError} className="shrink-0 text-[10px] underline">忽略</button>
        </div>
      )}

      {snapshot && snapshot.endReason === 'build-failed' && snapshot.buildDiagnostics.length > 0 && (
        <div className="border-b border-edge-soft px-3 py-1.5">
          <div className="mb-1 text-[11px] font-medium text-danger">编译失败（调试器未启动）</div>
          <ul>
            {snapshot.buildDiagnostics.slice(0, 6).map((d, i) => (
              <li key={i} className="font-mono text-[11px] text-danger">
                {d.file}{d.line ? `:${d.line}` : ''}{d.column ? `:${d.column}` : ''} — {d.message}
              </li>
            ))}
          </ul>
          {snapshot.buildStdout && <pre className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap rounded bg-panel px-2 py-1 font-mono text-[10px] text-ink-faint">{snapshot.buildStdout.slice(0, 1200)}</pre>}
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2">
        {/* 调用栈 */}
        {snapshot && snapshot.stackFrames.length > 0 && (
          <section className="mb-3">
            <div className="mb-1 text-[11px] font-medium text-ink-faint">调用栈（{snapshot.stackFrames.length} 帧）</div>
            <ul>
              {snapshot.stackFrames.map((frame, i) => (
                <li key={frame.id}>
                  <button
                    type="button"
                    onClick={() => {
                      selectFrame(frame.id)
                      if (frame.file) onOpenFile?.(frame.file)
                    }}
                    className={`flex w-full items-baseline gap-2 rounded px-1.5 py-0.5 text-left font-mono text-[11px] hover:bg-panel-2 ${
                      (selectedFrameId ?? snapshot?.stackFrames[0]?.id) === frame.id ? 'bg-accent-soft text-ink' : i === 0 ? 'text-warn' : 'text-ink-dim'
                    }`}
                  >
                    <span className="w-4 shrink-0 text-right text-ink-faint">{i === 0 ? '▶' : i}</span>
                    <span className="truncate">{frame.name}</span>
                    {frame.file && <span className="ml-auto shrink-0 text-[10px] text-ink-faint">{frame.file}{frame.line ? `:${frame.line}` : ''}</span>}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* 作用域与变量（顶帧） */}
        {snapshot && activeScopes.length > 0 && (
          <section className="mb-3">
            <div className="mb-1 text-[11px] font-medium text-ink-faint">
              变量（{selectedFrameId !== null ? `帧 #${selectedFrameId}` : '当前栈帧'}）
            </div>
            {activeScopes.map((scope) => (
              <div key={scope.name} className="mb-1.5">
                <div className="px-1 text-[10px] font-medium uppercase tracking-wide text-ink-faint">{scope.name}</div>
                {scope.variables.length === 0 ? (
                  <div className="px-5 text-[10px] text-ink-faint">（空）</div>
                ) : (
                  scope.variables.map((v) => <ValueVariable key={v.name} variable={v} depth={0} />)
                )}
              </div>
            ))}
          </section>
        )}

        {/* 线程 */}
        {snapshot && snapshot.threads.length > 0 && (
          <section>
            <div className="mb-1 text-[11px] font-medium text-ink-faint">线程</div>
            <ul className="font-mono text-[11px] text-ink-dim">
              {snapshot.threads.map((t) => (
                <li key={t.id} className="px-1.5 py-0.5">
                  {t.isPrimary ? '●' : '○'} {t.name} <span className="text-ink-faint">(id {t.id})</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* 程序输出（调试期间真实 stdout/stderr） */}
        {snapshot && (snapshot.programOutput?.length ?? 0) > 0 && (
          <section className="mb-3">
            <div className="mb-1 text-[11px] font-medium text-ink-faint">程序输出</div>
            <pre className="max-h-40 overflow-y-auto rounded border border-edge-soft bg-panel px-2 py-1 font-mono text-[10px] leading-relaxed">
              {(snapshot.programOutput ?? []).slice(-60).map((line, i) => (
                <div key={i} className={line.category === 'stderr' ? 'text-danger' : line.category === 'system' ? 'text-ink-faint' : 'text-ink-dim'}>
                  {line.text}
                </div>
              ))}
            </pre>
          </section>
        )}

        {/* 断点验证 */}
        {snapshot && snapshot.breakpoints.length > 0 && (
          <section className="mt-3">
            <div className="mb-1 text-[11px] font-medium text-ink-faint">断点</div>
            <ul className="font-mono text-[11px]">
              {snapshot.breakpoints.map((bp, i) => (
                <li key={i} className={`px-1.5 py-0.5 ${bp.verified ? 'text-ink-dim' : 'text-danger'}`}>
                  {bp.verified ? '●' : '○'} {bp.path}:{bp.line}
                  {!bp.verified && <span className="ml-2 text-[10px]">未绑定{bp.message ? `：${bp.message}` : ''}</span>}
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  )
}
