import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { deleteProject, listProjects } from '../api/projects'
import { ApiError } from '../api/client'
import type { Project } from '../types/project'
import { Badge } from '../components/ui/Badge'
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

import { BlurFade } from '../components/ui/upstream/blur-fade'
import { AnimatePresence, motion } from 'motion/react'
import { useUiReducedMotion } from '../hooks/useUiReducedMotion'
import { FolderCode, ArrowUpRight, Plus, Network, ArrowRight, Code2, Route, ScanLine, Trash2, GitBranch, Sparkles } from 'lucide-react'

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

interface ProjectCardProps {
  project: Project
  onDelete?: (project: Project) => void
}

function ProjectCard({ project, onDelete }: ProjectCardProps) {
  return (
    <article className="project-surface group rounded-xl border border-edge-soft bg-panel p-6 transition-colors hover:border-edge lg:p-7">
      <div className="mb-7 flex items-center justify-between">
        <FolderCode className="size-7 text-accent" strokeWidth={1.5} />
        <div className="flex items-center gap-2">
          <Badge tone={statusTone(project.status)}><span className="mr-1.5 size-1 rounded-full bg-current" />{STATUS_LABELS[project.status]}</Badge>
          {onDelete && (
            <button
              type="button"
              title="删除项目"
              aria-label={`删除项目 ${project.title}`}
              onClick={() => onDelete(project)}
              className="rounded-md p-1.5 text-ink-faint opacity-0 transition-opacity hover:bg-danger/10 hover:text-danger focus-visible:opacity-100 group-hover:opacity-100"
            >
              <Trash2 className="size-4" />
            </button>
          )}
        </div>
      </div>
      <h2 className="mb-3 text-xl font-semibold tracking-tight"><Link to={`/projects/${project.id}`} className="hover:text-accent">{project.title}</Link></h2>
      {project.description && (
        <p className="mb-5 max-w-[65ch] text-sm leading-7 text-ink-dim">
          {project.description}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Badge>{MODE_LABELS[project.mode]}</Badge>
        <Badge>复杂度 · {COMPLEXITY_LABELS[project.complexity]}</Badge>
        {project.stack.slice(0, 4).map((tech) => (
          <span
            key={tech}
            className="rounded-md bg-panel-2 px-2 py-1 text-[11px] text-ink-dim"
          >
            {tech}
          </span>
        ))}
      </div>
      <div className="mt-7 flex flex-wrap items-center justify-between gap-3 border-t border-edge-soft pt-5">
        <span className="text-[11px] text-ink-faint">创建于 {formatDateTime(project.createdAt)} · 规格 v{project.specVersion}</span>
        <Button asChild size="sm" variant="outline"><Link to={`/projects/${project.id}/ide`}>打开工作区<ArrowUpRight className="size-3.5" /></Link></Button>
      </div>
    </article>
  )
}

export default function DashboardPage() {
  const reduced = useUiReducedMotion()
  const [projects, setProjects] = useState<Project[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState<Project | null>(null)
  const [deleting, setDeleting] = useState(false)

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

  const handleDelete = useCallback(async () => {
    if (!confirmDelete) return
    setDeleting(true)
    try {
      await deleteProject(confirmDelete.id)
      setConfirmDelete(null)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除失败')
    } finally {
      setDeleting(false)
    }
  }, [confirmDelete, load])

  return (
    <div className="mx-auto min-h-full max-w-[1180px] px-6 py-10 lg:px-10 lg:py-12">
      <header className="mb-12 flex flex-wrap items-center justify-between gap-5">
        <div>
          <h1 className="text-[32px] font-semibold tracking-tight lg:text-[36px]">项目工作台</h1>
          <p className="mt-3 text-[15px] leading-7 text-ink-dim">从想法到运行，在真实项目中理解代码。</p>
        </div>
        <div className="flex items-center gap-3">
          <Button asChild className="h-10 px-4" variant="outline">
            <Link to="/courses/new"><GitBranch className="size-4" />从 GitHub 生成课程</Link>
          </Button>
          <Button className="h-10 px-4" onClick={() => setCreating((value) => !value)} variant={creating ? 'outline' : 'primary'}>
            <Plus className="size-4" />{creating ? '收起表单' : '新建项目'}
          </Button>
        </div>
      </header>

      <AnimatePresence initial={false}>
        {creating && <motion.section initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} transition={{ duration: reduced ? 0 : 0.2 }} className="mb-8 overflow-hidden rounded-xl border border-edge bg-panel">
          <div className="border-b border-edge-soft px-5 py-4"><h2 className="text-sm font-semibold">定义项目目标</h2></div>
          <div className="p-5"><CreateProjectForm onDone={() => setCreating(false)} /></div>
        </motion.section>}
      </AnimatePresence>

      <div className="grid items-start gap-10 xl:grid-cols-[minmax(0,1fr)_260px]">
      <main className="min-w-0">
        <div className="mb-5 flex items-center gap-3"><h2 className="text-sm font-semibold">我的项目</h2><span className="rounded-md bg-panel-2 px-2 py-0.5 text-xs text-ink-faint">{projects ? `${projects.length} 个项目` : '正在同步…'}</span></div>
        {error && <ErrorBanner message={error} onRetry={() => void load()} />}
        {!error && projects === null && <Spinner label="正在加载项目列表…" />}
        {!error && projects !== null && projects.length === 0 && (
          <div className="space-y-4">
            <EmptyState
              title="还没有项目"
              description="两种方式开始学习：手动创建项目，或让 AI 从 GitHub 仓库自动生成完整课程。"
            >
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <Button asChild size="sm">
                  <Link to="/courses/new"><GitBranch className="size-4" />从 GitHub 生成课程</Link>
                </Button>
                <Button size="sm" variant="outline" onClick={() => setCreating(true)}>
                  <Plus className="size-4" />手动创建项目
                </Button>
              </div>
            </EmptyState>
            <Link to="/courses/new" className="group block rounded-xl border border-edge-soft bg-panel p-5 transition-colors hover:border-accent/40">
              <div className="flex items-start gap-4">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent"><Sparkles className="size-5" /></span>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-ink group-hover:text-accent">AI 自动生成项目课程</p>
                  <p className="mt-1 text-xs leading-5 text-ink-faint">输入一个 GitHub 仓库地址，AI 自动分析代码、拆解任务、生成测试并验证——然后你从零开始逐阶段实现这个项目。</p>
                </div>
                <ArrowRight className="ml-auto mt-1 size-4 shrink-0 text-ink-faint group-hover:text-accent" />
              </div>
            </Link>
          </div>
        )}
        {!error && projects !== null && projects.length > 0 && (
          <div className="space-y-4">
            {projects.map((project) => (
              <BlurFade key={project.id} delay={0.035} duration={0.25} offset={3} blur="2px"><ProjectCard project={project} onDelete={setConfirmDelete} /></BlurFade>
            ))}
          </div>
        )}
      </main>

      <aside className="border-t border-edge-soft pt-5 xl:mt-10 xl:border-t-0 xl:pt-0">
        <h2 className="mb-2 text-sm font-semibold">在项目中学习</h2>
        <p className="mb-6 text-xs leading-6 text-ink-faint">从能力诊断出发，在代码和反馈之间逐步建立理解。</p>
        {projects?.[0] && <div className="space-y-1">
          {[{ title: '了解当前能力', description: '开始项目能力诊断', icon: ScanLine, to: `/projects/${projects[0].id}/assessment` },
            { title: '查看学习路线', description: '任务与先修知识', icon: Route, to: `/projects/${projects[0].id}` },
            { title: '进入代码工作区', description: '编辑、运行与测试', icon: Code2, to: `/projects/${projects[0].id}/ide` }].map(({ title, description, icon: Icon, to }) =>
              <Link key={title} to={to} className="group flex items-start gap-3 rounded-lg py-3 text-ink-dim hover:text-ink"><Icon className="mt-0.5 size-4 shrink-0 text-ink-faint group-hover:text-accent" /><span><span className="block text-[13px] font-medium">{title}</span><span className="mt-1 block text-xs text-ink-faint">{description}</span></span><ArrowRight className="ml-auto mt-0.5 size-3.5 text-ink-faint" /></Link>)}
        </div>}
        <Link to="/concepts" className="mt-6 flex items-center gap-2 border-t border-edge-soft pt-5 text-xs text-accent hover:text-ink"><Network className="size-4" />探索知识之间的联系<ArrowUpRight className="ml-auto size-3.5" /></Link>
        <Link to="/courses/new" className="mt-2 flex items-center gap-2 text-xs text-accent hover:text-ink"><Sparkles className="size-4" />从 GitHub 生成课程<ArrowUpRight className="ml-auto size-3.5" /></Link>
      </aside>
      </div>

      <footer className="mt-16 flex flex-wrap items-center justify-between gap-3 border-t border-edge-soft pt-5 text-[11px] leading-relaxed text-ink-faint">
        <span>代码编辑、浏览器运行与测试、能力诊断、学习路线已接入真实数据。</span>
        <Link to="/concepts" className="inline-flex items-center gap-1 text-ink-dim hover:text-ink">探索知识依赖<ArrowUpRight className="size-3" /></Link>
      </footer>

      {/* 删除确认对话框 */}
      <AnimatePresence initial={false}>
        {confirmDelete && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: reduced ? 0 : 0.15 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
            onClick={() => !deleting && setConfirmDelete(null)}
            role="dialog"
            aria-modal="true"
            aria-label="删除项目确认"
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              transition={{ duration: reduced ? 0 : 0.15 }}
              className="max-w-md rounded-xl border border-edge-soft bg-panel p-6 shadow-xl"
              onClick={(e) => e.stopPropagation()}
            >
              <h3 className="mb-2 text-base font-semibold text-ink">删除项目</h3>
              <p className="mb-1 text-sm leading-6 text-ink-dim">
                确定要删除「{confirmDelete.title}」吗？
              </p>
              <p className="mb-5 text-xs leading-5 text-ink-faint">
                将级联删除该项目的全部文件、代码快照、任务、学习计划、教学记录与学习事件，操作不可撤销。
              </p>
              <div className="flex justify-end gap-3">
                <Button size="sm" variant="ghost" disabled={deleting} onClick={() => setConfirmDelete(null)}>
                  取消
                </Button>
                <Button size="sm" variant="danger" disabled={deleting} onClick={() => void handleDelete()}>
                  {deleting ? '删除中…' : '确认删除'}
                </Button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
