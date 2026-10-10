import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listProjects } from '../api/projects'
import { ApiError } from '../api/client'
import type { Project } from '../types/project'
import { Badge } from '../components/ui/Badge'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { ErrorBanner, Spinner } from '../components/ui/Feedback'
import { EmptyState } from '../components/ui/PlaceholderState'
import { CreateProjectForm } from '../components/projects/CreateProjectForm'
import {
  COMPLEXITY_LABELS,
  MODE_LABELS,
  STATUS_LABELS,
  formatDateTime,
} from '../lib/labels'

function statusTone(status: Project['status']) {
  switch (status) {
    case 'active':
      return 'info' as const
    case 'completed':
      return 'ok' as const
    case 'archived':
      return 'neutral' as const
    default:
      return 'neutral' as const
  }
}

function ProjectCard({ project }: { project: Project }) {
  return (
    <Link
      to={`/projects/${project.id}`}
      className="group block rounded-lg border border-edge bg-panel p-4 transition-colors hover:border-accent/50"
    >
      <div className="mb-2 flex items-start justify-between gap-3">
        <h2 className="font-semibold text-ink group-hover:text-white">
          {project.title}
        </h2>
        <Badge tone={statusTone(project.status)}>{STATUS_LABELS[project.status]}</Badge>
      </div>
      {project.description && (
        <p className="mb-3 line-clamp-2 text-sm leading-relaxed text-ink-dim">
          {project.description}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <Badge>{MODE_LABELS[project.mode]}</Badge>
        <Badge>复杂度 · {COMPLEXITY_LABELS[project.complexity]}</Badge>
        {project.stack.slice(0, 4).map((tech) => (
          <span
            key={tech}
            className="rounded bg-panel-2 px-1.5 py-0.5 font-mono text-[11px] text-ink-dim"
          >
            {tech}
          </span>
        ))}
      </div>
      <div className="mt-3 border-t border-edge-soft pt-2 text-[11px] text-ink-faint">
        创建于 {formatDateTime(project.createdAt)} · 规格 v{project.specVersion}
      </div>
    </Link>
  )
}

export default function DashboardPage() {
  const [projects, setProjects] = useState<Project[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)

  const load = useCallback(async () => {
    setError(null)
    try {
      setProjects(await listProjects())
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '未知错误')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <div className="mx-auto min-h-full max-w-6xl px-6 py-10">
      <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5">
            <span className="grid size-9 place-items-center rounded-lg border border-edge bg-panel font-mono text-lg text-accent">
              ⬡
            </span>
            <div>
              <h1 className="text-xl font-bold tracking-tight">ProjectWeave</h1>
              <p className="text-xs text-ink-dim">真实项目驱动的 AI 编程学习工作台</p>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Link
            to="/concepts"
            className="rounded-md border border-edge px-3 py-1.5 text-xs text-ink-dim transition-colors hover:border-accent/50 hover:text-ink"
          >
            知识图谱
          </Link>
          <Button onClick={() => setCreating((value) => !value)} variant={creating ? 'outline' : 'primary'}>
            {creating ? '收起表单' : '+ 新建项目'}
          </Button>
        </div>
      </header>

      {creating && (
        <Card title="定义项目目标" className="mb-8">
          <CreateProjectForm onDone={() => setCreating(false)} />
        </Card>
      )}

      <main>
        <h2 className="mb-3 text-sm font-semibold text-ink-dim">我的项目</h2>
        {error && <ErrorBanner message={error} onRetry={() => void load()} />}
        {!error && projects === null && <Spinner label="正在加载项目列表…" />}
        {!error && projects !== null && projects.length === 0 && (
          <EmptyState
            title="还没有项目"
            description="从描述一个你真正想完成的软件项目开始。系统会围绕它生成学习路线（课程引擎接入后）。"
          >
            <Button size="sm" variant="outline" onClick={() => setCreating(true)} className="mt-3">
              创建第一个项目
            </Button>
          </EmptyState>
        )}
        {!error && projects !== null && projects.length > 0 && (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {projects.map((project) => (
              <ProjectCard key={project.id} project={project} />
            ))}
          </div>
        )}
      </main>

      <footer className="mt-12 border-t border-edge-soft pt-4 text-[11px] leading-relaxed text-ink-faint">
        P0 骨架阶段：项目目标录入与持久化已可用；AI 需求分析、能力诊断、课程生成、代码执行、AI
        教学与交互式可视化均未实现，将在后续阶段交付。
      </footer>
    </div>
  )
}
