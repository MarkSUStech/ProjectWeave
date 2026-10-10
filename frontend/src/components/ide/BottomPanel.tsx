import { useCallback, useEffect, useRef, useState } from 'react'
import { PlaceholderState } from '../ui/PlaceholderState'
import { Button } from '../ui/Button'
import { useRunStore } from '../../stores/runStore'
import { useTestStore } from '../../stores/testStore'
import { listEvents } from '../../api/events'
import { ApiError } from '../../api/client'
import { formatClock, formatDateTime } from '../../lib/labels'
import type { LearningEvent, TerminalEntry, TestFileResult } from '../../types'

const TABS = [
  { id: 'terminal', label: '终端' },
  { id: 'tests', label: '测试' },
  { id: 'events', label: '学习事件' },
] as const

const ENTRY_CLASSES: Record<TerminalEntry['kind'], string> = {
  system: 'text-ink-faint italic',
  log: 'text-ink-dim',
  info: 'text-accent',
  warn: 'text-warn',
  error: 'text-danger',
}

const TYPE_LABELS: Record<string, string> = {
  'file-saved': '保存',
  'code-run': '运行',
  'tests-run': '测试',
  'assessment-submitted': '诊断',
  'plan-generated': '路线生成',
  'plan-replanned': '重新规划',
}

function payloadSummary(event: LearningEvent): string {
  const payload = event.payload
  const parts: string[] = []
  if (typeof payload.path === 'string') parts.push(payload.path)
  if (typeof payload.planVersion === 'number') parts.push(`v${payload.planVersion}`)
  if (typeof payload.questions === 'number') {
    parts.push(`${payload.questions} 题${typeof payload.mastered === 'number' ? ` · ${payload.mastered} 掌握` : ''}`)
  }
  if (typeof payload.status === 'string') parts.push(payload.status)
  if (typeof payload.passed === 'number' && typeof payload.failed === 'number') {
    parts.push(`${payload.passed} 通过 / ${payload.failed} 失败`)
  }
  return parts.join(' · ') || JSON.stringify(payload).slice(0, 80)
}

/** 学习事件页签：服务端事件日志的实时视图（可刷新）。 */
function EventsView({ projectId }: { projectId: string }) {
  const [events, setEvents] = useState<LearningEvent[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      setEvents(await listEvents(projectId))
    } catch (err) {
      setEvents([])
      setError(err instanceof ApiError ? err.message : '事件加载失败')
    }
  }, [projectId])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center justify-between border-b border-edge-soft px-3 py-1">
        <span className="text-[11px] text-ink-faint">
          学习事件日志 · 幂等信封 v1（保存/运行/测试/诊断/规划）
        </span>
        <button
          type="button"
          onClick={() => void load()}
          className="rounded px-1.5 py-0.5 text-[11px] text-ink-faint hover:text-ink"
        >
          刷新
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-1.5">
        {error && <p className="py-1 text-xs text-danger">{error}</p>}
        {events === null && !error && <p className="py-2 text-xs text-ink-faint">加载中…</p>}
        {events !== null && events.length === 0 && !error && (
          <p className="py-2 text-xs text-ink-faint">暂无事件。保存文件、运行代码或完成诊断后会出现记录。</p>
        )}
        <ul className="space-y-0.5 font-mono text-xs leading-relaxed">
          {events?.map((event) => (
            <li key={event.eventId} className="text-ink-dim">
              <span className="mr-2 select-none text-[10px] text-ink-faint/60">
                {formatClock(event.occurredAt)}
              </span>
              <span className="mr-2 rounded bg-panel-2 px-1.5 py-0.5 text-[10px] text-accent">
                {TYPE_LABELS[event.type] ?? event.type}
              </span>
              <span title={formatDateTime(event.occurredAt)}>{payloadSummary(event)}</span>
              <span className="ml-2 text-[10px] text-ink-faint/60">#{event.sequence}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

function TerminalView() {
  const entries = useRunStore((state) => state.entries)
  const running = useRunStore((state) => state.running)
  const clear = useRunStore((state) => state.clear)
  const listRef = useRef<HTMLDivElement>(null)

  // 新输出时自动滚动到底部
  useEffect(() => {
    const list = listRef.current
    if (list) list.scrollTop = list.scrollHeight
  }, [entries])

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center justify-between border-b border-edge-soft px-3 py-1">
        <span className="text-[11px] text-ink-faint">
          浏览器运行器 · 隔离 Worker（无 DOM / 应用状态访问）
          {running && <span className="ml-2 text-accent">● 运行中</span>}
        </span>
        <button
          type="button"
          onClick={clear}
          className="rounded px-1.5 py-0.5 text-[11px] text-ink-faint hover:text-ink"
        >
          清空
        </button>
      </div>
      <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto px-3 py-1.5">
        {entries.length === 0 ? (
          <p className="py-2 font-mono text-xs text-ink-faint">
            尚无输出。打开 .js / .ts 文件后点击「▶ 运行」（Ctrl+Enter）。
          </p>
        ) : (
          <ul className="space-y-0.5 font-mono text-xs leading-relaxed">
            {entries.map((entry) => (
              <li key={entry.id} className={`whitespace-pre-wrap break-all ${ENTRY_CLASSES[entry.kind]}`}>
                <span className="mr-2 select-none text-[10px] text-ink-faint/60">
                  {formatClock(entry.at)}
                </span>
                {entry.text}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

function fileBadgeTone(status: TestFileResult['status']) {
  if (status === 'passed') return 'text-ok'
  if (status === 'failed') return 'text-danger'
  return 'text-warn'
}

function fileBadgeText(result: TestFileResult): string {
  if (result.status === 'error') return '✘ 加载/执行错误'
  const passed = result.cases.filter((c) => c.status === 'passed').length
  const failed = result.cases.length - passed
  return `${failed > 0 ? '✘' : '✔'} ${passed} 通过${failed > 0 ? ` / ${failed} 失败` : ''}`
}

function TestView({ onRun }: { onRun: () => void }) {
  const { running, results, progress, lastRunAt } = useTestStore()

  if (results.length === 0 && !running) {
    return (
      <PlaceholderState
        title="测试面板"
        description="约定 *.test.ts / *.test.js 为测试文件（提供 describe / it / expect 断言）。项目存在测试文件后，点击「运行测试」在浏览器 Worker 沙箱中执行。"
      >
        <Button size="sm" variant="outline" onClick={onRun} className="mt-2">
          ▶ 运行测试
        </Button>
      </PlaceholderState>
    )
  }

  const totalPassed = results.reduce((sum, file) => sum + file.cases.filter((c) => c.status === 'passed').length, 0)
  const totalFailed = results.reduce((sum, file) => sum + file.cases.filter((c) => c.status === 'failed').length, 0)

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center justify-between border-b border-edge-soft px-3 py-1">
        <span className="text-[11px] text-ink-faint">
          浏览器测试运行器 · describe / it / expect
          {running && progress && (
            <span className="ml-2 text-accent">
              ● 运行中 {progress.done}/{progress.total}
            </span>
          )}
          {!running && lastRunAt && (
            <span className="ml-2">
              合计 <span className={totalFailed > 0 ? 'text-danger' : 'text-ok'}>{totalPassed} 通过</span>
              {totalFailed > 0 && <span className="text-danger"> / {totalFailed} 失败</span>}
            </span>
          )}
        </span>
        <Button size="sm" variant="outline" disabled={running} onClick={onRun}>
          {running ? '运行中…' : '▶ 运行测试'}
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-1.5">
        <ul className="space-y-2 font-mono text-xs">
          {results.map((file) => (
            <li key={file.path} className="rounded border border-edge-soft">
              <div className={`flex items-center justify-between border-b border-edge-soft px-2.5 py-1 ${fileBadgeTone(file.status)}`}>
                <span className="truncate">{file.path}</span>
                <span className="shrink-0">{fileBadgeText(file)}</span>
              </div>
              {file.error && (
                <div className="whitespace-pre-wrap break-all px-2.5 py-1.5 text-warn">{file.error}</div>
              )}
              <ul>
                {file.cases.map((testCase, index) => (
                  <li key={index} className="border-b border-edge-soft/50 px-2.5 py-1 last:border-b-0">
                    <div className="flex items-start justify-between gap-3">
                      <span className={testCase.status === 'passed' ? 'text-ok' : 'text-danger'}>
                        {testCase.status === 'passed' ? '✔' : '✘'} {testCase.name}
                      </span>
                      <span className="shrink-0 text-[10px] text-ink-faint">{testCase.durationMs}ms</span>
                    </div>
                    {testCase.error && (
                      <div className="mt-0.5 whitespace-pre-wrap break-all rounded bg-danger/10 px-2 py-1 text-danger">
                        {testCase.error}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

/** 底部面板：终端 / 测试（真实浏览器运行器）/ 学习事件（真实日志）。 */
export function BottomPanel({ onRunTests, projectId }: { onRunTests: () => void; projectId: string }) {
  const tab = useRunStore((state) => state.activeTab)
  const setTab = useRunStore((state) => state.setActiveTab)

  return (
    <div className="flex min-h-0 flex-col border-t border-edge bg-panel">
      <div className="flex items-center gap-1 border-b border-edge-soft px-2">
        {TABS.map(({ id, label }) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={`border-b-2 px-3 py-1.5 text-xs transition-colors ${
              tab === id
                ? 'border-accent text-ink'
                : 'border-transparent text-ink-faint hover:text-ink-dim'
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {tab === 'terminal' && <TerminalView />}
        {tab === 'tests' && <TestView onRun={onRunTests} />}
        {tab === 'events' && <EventsView projectId={projectId} />}
      </div>
    </div>
  )
}
