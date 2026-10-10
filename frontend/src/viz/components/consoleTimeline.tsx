/**
 * L1 标准组件：执行时间线（console timeline）。
 *
 * 数据绑定 run:latest —— 渲染最近一次浏览器运行的真实输出（runtime 来源，
 * §9.2"真实执行"标签）。本地交互（点击展开条目详情）由组件自行处理，
 * 不调用 LLM（§9.1）。
 */
import { useMemo, useState } from 'react'
import { useRunStore } from '../../stores/runStore'
import type { TerminalEntry } from '../../types/runner'

const LEVEL_COLORS: Record<TerminalEntry['kind'], string> = {
  system: 'border-ink-faint/40',
  log: 'border-accent/60',
  info: 'border-accent',
  warn: 'border-warn',
  error: 'border-danger',
}

const LEVEL_DOTS: Record<TerminalEntry['kind'], string> = {
  system: 'bg-ink-faint',
  log: 'bg-accent',
  info: 'bg-accent',
  warn: 'bg-warn',
  error: 'bg-danger',
}

export function ConsoleTimelineView({ config }: { instanceId: string; config: Record<string, unknown> }) {
  const allEntries = useRunStore((state) => state.entries)
  const entries = useMemo(
    () => allEntries.filter((entry) => entry.kind !== 'system'),
    [allEntries],
  )
  const [selected, setSelected] = useState<number | null>(null)
  const limit = typeof config.maxEntries === 'number' ? config.maxEntries : 50
  const visible = useMemo(() => entries.slice(-limit), [entries, limit])

  if (visible.length === 0) {
    return (
      <div className="flex h-full items-center justify-center p-4 text-center text-xs leading-relaxed text-ink-faint">
        还没有运行输出。运行一个 .js / .ts 文件后，这里的每条输出会按时间排成时间线。
      </div>
    )
  }

  const firstAt = new Date(visible[0].at).getTime()

  return (
    <div className="h-full overflow-y-auto p-3">
      <ol className="relative space-y-1.5 border-l border-edge pl-4" data-testid="console-timeline">
        {visible.map((entry) => {
          const offsetMs = new Date(entry.at).getTime() - firstAt
          const isSelected = selected === entry.id
          return (
            <li key={entry.id} className="relative">
              <span
                className={`absolute -left-[21px] top-1.5 size-2 rounded-full ${LEVEL_DOTS[entry.kind]}`}
                title={entry.kind}
              />
              <button
                type="button"
                onClick={() => setSelected(isSelected ? null : entry.id)}
                className={`w-full rounded border-l-2 bg-panel-2/60 px-2.5 py-1.5 text-left transition-colors hover:bg-panel-2 ${LEVEL_COLORS[entry.kind]}`}
              >
                <span className="mr-2 select-none font-mono text-[10px] text-ink-faint">
                  +{String(Math.max(0, offsetMs)).padStart(4, '0')}ms
                </span>
                <span className="font-mono text-xs text-ink-dim">{entry.text}</span>
              </button>
              {isSelected && (
                <div className="mt-1 rounded border border-edge-soft bg-panel px-2.5 py-1.5 text-[11px] leading-relaxed text-ink-faint">
                  <div>级别：{entry.kind}</div>
                  <div>时间：{new Date(entry.at).toLocaleTimeString('zh-CN', { hour12: false })}</div>
                  <div>条目 #{entry.id}</div>
                </div>
              )}
            </li>
          )
        })}
      </ol>
    </div>
  )
}
