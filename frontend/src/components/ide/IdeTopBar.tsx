import { Link } from 'react-router-dom'
import { Badge } from '../ui/Badge'
import { WORKSPACE_MODES } from '../../types/ide'
import { useIdeUiStore } from '../../stores/ideUiStore'
import { STATUS_LABELS } from '../../lib/labels'
import { MODE_LABELS, getSettings, updateSettings, type InterventionMode } from '../../api/settings'
import { useEffect, useState, type ReactNode } from 'react'
import { motion } from 'motion/react'
import { ArrowLeft, LockKeyhole, UnlockKeyhole, Code2, Bug, FlaskConical, Workflow } from 'lucide-react'
import { ErrorBanner } from '../ui/Feedback'
import { Tooltip, TooltipTrigger, TooltipContent } from '../ui/upstream/tooltip'
import type { Project } from '../../types/project'
import { SettingsButton } from '../settings/SettingsButton'
import { useUiReducedMotion } from '../../hooks/useUiReducedMotion'

const INTERVENTION_MODES: InterventionMode[] = ['quiet', 'adaptive', 'guided']
const MODE_ICONS = { coding: Code2, debugging: Bug, 'visual-learning': FlaskConical, architecture: Workflow }

/** 顶栏：项目信息 + 四种工作模式 + 介入模式 + 布局锁定（设计 3.2 / 10.1 / 8.2）。 */
export function IdeTopBar({ project, commands }: { project: Project; commands?: ReactNode }) {
  const { mode, locked, setMode, toggleLock } = useIdeUiStore()
  const reduced = useUiReducedMotion()
  const [settingsError, setSettingsError] = useState<string | null>(null)
  const [updating, setUpdating] = useState(false)
  const [intervention, setIntervention] = useState<InterventionMode>('adaptive')

  useEffect(() => {
    getSettings().then(setIntervention).catch(() => setSettingsError('AI 偏好加载失败，请刷新页面重试'))
  }, [])

  const switchIntervention = async (next: InterventionMode) => {
    if (updating) return
    setSettingsError(null)
    setUpdating(true)
    const previous = intervention
    setIntervention(next)
    try {
      await updateSettings(next)
    } catch {
      setIntervention(previous) // 失败回滚，不假装成功
      setSettingsError('AI 偏好保存失败，请重试')
    } finally {
      setUpdating(false)
    }
  }

  return (
    <div className="shrink-0">
    <header className="workspace-chrome flex h-16 min-w-0 items-center gap-4 border-b border-edge-soft px-4">
      <Link
        to={`/projects/${project.id}`}
        title="返回项目详情"
        className="grid size-8 shrink-0 place-items-center rounded-lg text-ink-faint hover:bg-panel-2 hover:text-ink"
      >
        <ArrowLeft className="size-4" />
      </Link>
      <div className="min-w-0 max-w-56">
        <div className="truncate text-sm font-semibold">{project.title}</div>
        <div className="flex items-center gap-2 text-[11px] text-ink-faint">
          <span>教学工作区</span>
          <Badge>{STATUS_LABELS[project.status]}</Badge>
        </div>
      </div>

      <nav
        className="mx-auto flex items-center gap-1 rounded-lg bg-app/50 p-1"
        aria-label="工作模式"
      >
        {WORKSPACE_MODES.map(({ value, label }) => {
          const Icon = MODE_ICONS[value]
          return (
          <button
            key={value}
            type="button"
            disabled={locked}
            onClick={() => setMode(value)}
            aria-pressed={mode === value}
            title={locked ? '布局已锁定，解锁后可切换' : `切换到「${label}」模式`}
            className={`relative isolate inline-flex items-center gap-2 rounded-md px-3 py-2 text-xs font-medium disabled:cursor-not-allowed ${
              mode === value
                ? 'text-ink'
                : 'text-ink-dim hover:text-ink disabled:hover:text-ink-faint'
            }`}
          >
            {mode === value && <motion.span layoutId="workspace-mode" className="workspace-nav-active absolute inset-0 -z-10 rounded-md bg-panel-2" transition={reduced ? { duration: 0 } : { type: 'spring', stiffness: 400, damping: 35 }} />}
            <Icon className={`size-3.5 ${mode === value ? 'text-accent' : ''}`} />
            {label}
          </button>
        )})}
      </nav>

      <div
        className="flex shrink-0 items-center gap-0.5 rounded-md p-0.5"
        aria-label="AI 介入模式"
        title="AI 介入模式：安静=仅你请求时响应；自适应=失败证据下的非阻塞建议；引导=允许主动点拨"
      >
        {INTERVENTION_MODES.map((value) => (
          <button
            key={value}
            type="button"
            disabled={updating}
            aria-pressed={intervention === value}
            onClick={() => void switchIntervention(value)}
            className={`rounded px-2 py-1 text-[11px] font-medium transition-colors ${
              intervention === value
                ? 'bg-panel-2 text-accent'
                : 'text-ink-faint hover:text-ink-dim'
            }`}
          >
            {MODE_LABELS[value]}
          </button>
        ))}
      </div>

      {commands}
      <SettingsButton />
      <Tooltip><TooltipTrigger asChild><button
        type="button"
        onClick={toggleLock}
        className={`shrink-0 rounded-md px-2.5 py-2 text-xs font-medium transition-colors ${
          locked
            ? 'bg-warn/10 text-warn'
            : 'text-ink-faint hover:bg-panel-2 hover:text-ink'
        }`}
        title="锁定后布局（含未来 AI 的布局建议）不可变更"
      >
        <span className="inline-flex items-center gap-1.5">{locked ? <LockKeyhole className="size-3.5" /> : <UnlockKeyhole className="size-3.5" />}{locked ? '布局已锁定' : '锁定布局'}</span>
      </button></TooltipTrigger><TooltipContent>锁定模式切换和面板尺寸，解锁后可拖动</TooltipContent></Tooltip>
    </header>
    {settingsError && <ErrorBanner message={settingsError} />}
    </div>
  )
}
