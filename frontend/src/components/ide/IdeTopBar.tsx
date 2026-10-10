import { Link } from 'react-router-dom'
import { Badge } from '../ui/Badge'
import { WORKSPACE_MODES, type WorkspaceMode } from '../../types/ide'
import { useIdeUiStore } from '../../stores/ideUiStore'
import { STATUS_LABELS } from '../../lib/labels'
import { MODE_LABELS, getSettings, updateSettings, type InterventionMode } from '../../api/settings'
import { useEffect, useState } from 'react'
import type { Project } from '../../types/project'

const INTERVENTION_MODES: InterventionMode[] = ['quiet', 'adaptive', 'guided']

/** 顶栏：项目信息 + 四种工作模式 + 介入模式 + 布局锁定（设计 3.2 / 10.1 / 8.2）。 */
export function IdeTopBar({ project }: { project: Project }) {
  const { mode, locked, setMode, toggleLock } = useIdeUiStore()
  const [intervention, setIntervention] = useState<InterventionMode>('adaptive')

  useEffect(() => {
    getSettings().then(setIntervention).catch(() => undefined)
  }, [])

  const switchIntervention = async (next: InterventionMode) => {
    const previous = intervention
    setIntervention(next)
    try {
      await updateSettings(next)
    } catch {
      setIntervention(previous) // 失败回滚，不假装成功
    }
  }

  return (
    <header className="flex min-w-0 items-center gap-3 border-b border-edge bg-panel px-3">
      <Link
        to={`/projects/${project.id}`}
        title="返回项目详情"
        className="shrink-0 rounded px-1.5 py-1 text-ink-dim hover:bg-panel-2 hover:text-ink"
      >
        ←
      </Link>
      <div className="min-w-0">
        <div className="truncate text-sm font-semibold">{project.title}</div>
        <div className="flex items-center gap-2 text-[11px] text-ink-faint">
          <span>任务：待生成（课程引擎未接入）</span>
          <Badge>{STATUS_LABELS[project.status]}</Badge>
        </div>
      </div>

      <nav
        className="mx-auto flex items-center rounded-md border border-edge bg-panel-2 p-0.5"
        aria-label="工作模式"
      >
        {WORKSPACE_MODES.map(({ value, label }) => (
          <button
            key={value}
            type="button"
            disabled={locked}
            onClick={() => setMode(value)}
            title={locked ? '布局已锁定，解锁后可切换' : `切换到「${label}」模式`}
            className={`rounded px-3 py-1 text-xs font-medium transition-colors disabled:cursor-not-allowed ${
              mode === value
                ? 'bg-accent text-white'
                : 'text-ink-dim hover:text-ink disabled:hover:text-ink-faint'
            }`}
          >
            {label}
          </button>
        ))}
      </nav>

      <div
        className="flex shrink-0 items-center rounded-md border border-edge bg-panel-2 p-0.5"
        aria-label="AI 介入模式"
        title="AI 介入模式：安静=仅你请求时响应；自适应=失败证据下的非阻塞建议；引导=允许主动点拨"
      >
        {INTERVENTION_MODES.map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => void switchIntervention(value)}
            className={`rounded px-2 py-1 text-[11px] font-medium transition-colors ${
              intervention === value
                ? 'bg-accent/80 text-white'
                : 'text-ink-faint hover:text-ink-dim'
            }`}
          >
            {MODE_LABELS[value]}
          </button>
        ))}
      </div>

      <button
        type="button"
        onClick={toggleLock}
        className={`shrink-0 rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors ${
          locked
            ? 'border-warn/50 bg-warn/10 text-warn'
            : 'border-edge text-ink-dim hover:border-accent/50 hover:text-ink'
        }`}
        title="锁定后布局（含未来 AI 的布局建议）不可变更"
      >
        {locked ? '🔒 布局已锁定' : '🔓 锁定布局'}
      </button>
    </header>
  )
}

/** 工作模式的布局参数（网格列 / 底栏高度）。 */
export function layoutFor(mode: WorkspaceMode): {
  columns: string
  rows: string
} {
  switch (mode) {
    case 'coding':
      return { columns: '240px minmax(0, 1fr) 320px', rows: '44px minmax(0, 1fr) 200px' }
    case 'debugging':
      return { columns: '240px minmax(0, 1fr) 320px', rows: '44px minmax(0, 1fr) 220px' }
    case 'visual-learning':
      return { columns: '240px minmax(0, 1fr) 320px', rows: '44px minmax(0, 1fr) 140px' }
    case 'architecture':
      return { columns: '240px minmax(0, 1fr) 0px', rows: '44px minmax(0, 1fr) 160px' }
  }
}
