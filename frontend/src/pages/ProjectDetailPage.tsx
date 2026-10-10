import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getProject } from '../api/projects'
import { getCodeVersion } from '../api/files'
import { listProjectAssessments } from '../api/assessments'
import { getPlan, replan } from '../api/plans'
import { ApiError } from '../api/client'
import type { Project } from '../types/project'
import type { CodeVersionInfo } from '../types/file'
import type { AssessmentBrief } from '../types/assessment'
import type { PlanDetail } from '../types/plan'
import { Badge } from '../components/ui/Badge'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { ErrorBanner, Spinner } from '../components/ui/Feedback'
import { EmptyState } from '../components/ui/PlaceholderState'
import {
  COMPLEXITY_LABELS,
  MODE_LABELS,
  STATUS_LABELS,
  formatDateTime,
} from '../lib/labels'

function ListBlock({ items }: { items: string[] }) {
  if (items.length === 0) return <p className="text-sm text-ink-faint">未填写</p>
  return (
    <ul className="space-y-1.5">
      {items.map((item, index) => (
        <li key={index} className="flex gap-2 text-sm leading-relaxed text-ink-dim">
          <span className="mt-2 size-1 shrink-0 rounded-full bg-accent/70" />
          {item}
        </li>
      ))}
    </ul>
  )
}

export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [project, setProject] = useState<Project | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [codeVersion, setCodeVersion] = useState<CodeVersionInfo | null>(null)
  const [latestAssessment, setLatestAssessment] = useState<AssessmentBrief | null>(null)
  const [plan, setPlan] = useState<PlanDetail | null>(null)
  const [planError, setPlanError] = useState<string | null>(null)
  const [replanning, setReplanning] = useState(false)

  const load = useCallback(async () => {
    if (!id) return
    setError(null)
    setProject(null)
    try {
      const loaded = await getProject(id)
      setProject(loaded)
      // 辅助信息独立加载：失败不阻塞页面。
      getCodeVersion(id).then(setCodeVersion).catch(() => setCodeVersion(null))
      listProjectAssessments(id)
        .then((items) => setLatestAssessment(items.find((s) => s.status === 'completed') ?? null))
        .catch(() => setLatestAssessment(null))
      setPlanError(null)
      getPlan(id).then(setPlan).catch(() => {
        setPlan(null)
        setPlanError('学习路线加载失败')
      })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '未知错误')
    }
  }, [id])

  const handleReplan = useCallback(async () => {
    if (!id || replanning) return
    setReplanning(true)
    setPlanError(null)
    try {
      const updated = await replan(id)
      setPlan(await getPlan(id))
      void updated
    } catch (err) {
      setPlanError(err instanceof ApiError ? err.message : '重新规划失败')
    } finally {
      setReplanning(false)
    }
  }, [id, replanning])

  useEffect(() => {
    void load()
  }, [load])

  if (error) {
    return (
      <div className="mx-auto max-w-3xl px-6 py-10">
        <Link to="/" className="mb-4 inline-block text-sm text-ink-dim hover:text-ink">
          ← 返回项目列表
        </Link>
        <ErrorBanner message={error} onRetry={() => void load()} />
      </div>
    )
  }
  if (!project) {
    return (
      <div className="mx-auto max-w-3xl px-6 py-10">
        <Spinner label="正在加载项目…" />
      </div>
    )
  }

  return (
    <div className="mx-auto min-h-full max-w-5xl px-6 py-10">
      <Link to="/" className="mb-4 inline-block text-sm text-ink-dim hover:text-ink">
        ← 返回项目列表
      </Link>

      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <Badge tone="info">{STATUS_LABELS[project.status]}</Badge>
            <Badge>{MODE_LABELS[project.mode]}</Badge>
            <Badge>复杂度 · {COMPLEXITY_LABELS[project.complexity]}</Badge>
          </div>
          <h1 className="text-2xl font-bold tracking-tight">{project.title}</h1>
          <p className="mt-1 font-mono text-xs text-ink-faint">id: {project.id}</p>
        </div>
        <Link to={`/projects/${project.id}/ide`}>
          <Button>打开教学 IDE →</Button>
        </Link>
      </header>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card title="项目描述" className="lg:col-span-2">
          {project.description ? (
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink-dim">
              {project.description}
            </p>
          ) : (
            <EmptyState title="暂无描述" description="创建项目时可以补充目标与背景说明。" />
          )}
        </Card>

        <Card title="元信息">
          <dl className="space-y-2.5 text-sm">
            {[
              ['规格版本', `v${project.specVersion}`],
              ['创建时间', formatDateTime(project.createdAt)],
              ['更新时间', formatDateTime(project.updatedAt)],
              ['所有者', `${project.ownerId}（开发模式）`],
              [
                '代码版本',
                codeVersion
                  ? `${codeVersion.codeVersion.slice(0, 19)}…（${codeVersion.fileCount} 个文件）`
                  : '不可用',
              ],
            ].map(([term, value]) => (
              <div key={term} className="flex justify-between gap-4">
                <dt className="shrink-0 text-ink-faint">{term}</dt>
                <dd className="truncate text-right font-mono text-xs text-ink-dim" title={value}>
                  {value}
                </dd>
              </div>
            ))}
          </dl>
        </Card>

        <Card title="目标功能" className="lg:col-span-2">
          <ListBlock items={project.targetFeatures} />
        </Card>

        <Card title="技术栈">
          {project.stack.length === 0 ? (
            <p className="text-sm text-ink-faint">未填写</p>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {project.stack.map((tech) => (
                <span
                  key={tech}
                  className="rounded border border-edge bg-panel-2 px-2 py-0.5 font-mono text-xs text-ink-dim"
                >
                  {tech}
                </span>
              ))}
            </div>
          )}
        </Card>

        <Card title="非目标（本期不做）" className="lg:col-span-2">
          <ListBlock items={project.nonGoals} />
        </Card>

        <Card title="验收标准">
          <ListBlock items={project.acceptanceCriteria} />
        </Card>

        <Card
          title="能力诊断"
          className="lg:col-span-3"
          actions={
            <Link
              to={`/projects/${project.id}/assessment`}
              className="rounded-md border border-edge px-3 py-1.5 text-xs text-ink-dim transition-colors hover:border-accent/50 hover:text-ink"
            >
              {latestAssessment ? '查看 / 重新诊断 →' : '开始诊断 →'}
            </Link>
          }
        >
          {latestAssessment?.results ? (
            <div className="flex flex-wrap items-center gap-3 text-sm">
              {(
                [
                  ['likely-mastered', 'text-ok'],
                  ['uncertain', 'text-warn'],
                  ['likely-gap', 'text-danger'],
                ] as const
              ).map(([label, cls]) => {
                const count = latestAssessment.results!.concepts.filter((c) => c.label === label).length
                return (
                  <span key={label} className={count > 0 ? cls : 'text-ink-faint'}>
                    {count} {label === 'likely-mastered' ? '已掌握' : label === 'uncertain' ? '不确定' : '疑似薄弱'}
                  </span>
                )
              })}
              <span className="text-xs text-ink-faint">
                最近诊断：{formatDateTime(latestAssessment.completedAt ?? latestAssessment.createdAt)}
                （规则化初判，置信度模型 P2.3 接入）
              </span>
            </div>
          ) : (
            <p className="text-sm leading-relaxed text-ink-faint">
              尚未完成诊断。诊断范围由项目技术栈反推（MVP 为客观预测题），结果将用于后续课程规划。
            </p>
          )}
        </Card>

        <Card
          title="学习路线"
          className="lg:col-span-3"
          actions={
            <div className="flex items-center gap-3">
              {plan && (
                <span className="text-[11px] text-ink-faint">路线 v{plan.plan.planVersion}</span>
              )}
              <button
                type="button"
                disabled={replanning || plan === null}
                onClick={() => void handleReplan()}
                className="rounded-md border border-edge px-3 py-1.5 text-xs text-ink-dim transition-colors hover:border-accent/50 hover:text-ink disabled:opacity-50"
              >
                {replanning ? '规划中…' : '↻ 重新规划'}
              </button>
            </div>
          }
        >
          {planError && <ErrorBanner message={planError} onRetry={() => void load()} />}
          {plan === null && !planError && <Spinner label="正在生成学习路线…" />}
          {plan && (
            <div className="space-y-3">
              <p className="text-xs leading-relaxed text-ink-faint">
                {plan.plan.reason}。任务图为样板课程模板（附录 B）；已完成诊断的概念按掌握证据跳过或补课。
              </p>
              <ol className="space-y-1.5">
                {plan.plan.activities.map((activity) => (
                  <li
                    key={activity.order}
                    className="flex items-start gap-2.5 rounded border border-edge-soft bg-panel-2 px-3 py-2"
                  >
                    <span className="shrink-0 font-mono text-[11px] text-ink-faint">
                      {activity.order}.
                    </span>
                    <div className="min-w-0">
                      <div className="text-sm text-ink">
                        {activity.type === 'learn-concept' ? '📖 学习概念 ' : '🛠 实践任务 '}
                        <span className="font-mono text-xs">
                          {activity.type === 'learn-concept' ? activity.conceptId : activity.title}
                        </span>
                      </div>
                      <div className="text-[11px] leading-relaxed text-ink-faint">
                        {activity.reason}
                      </div>
                    </div>
                  </li>
                ))}
              </ol>
              {plan.plan.skipped.length > 0 && (
                <details className="rounded border border-edge-soft px-3 py-2">
                  <summary className="cursor-pointer text-xs text-ink-dim">
                    已跳过 {plan.plan.skipped.length} 个概念（判定已掌握）
                  </summary>
                  <ul className="mt-2 space-y-1">
                    {plan.plan.skipped.map((skipped) => (
                      <li key={skipped.conceptId} className="text-[11px] text-ink-faint">
                        <span className="font-mono">{skipped.conceptId}</span> — {skipped.reason}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          )}
        </Card>

        <Card title="项目里程碑（样板课程任务图）" className="lg:col-span-3">
          {plan === null ? (
            planError ? (
              <p className="text-sm text-ink-faint">任务图随学习路线生成，当前不可用。</p>
            ) : (
              <Spinner label="加载任务图…" />
            )
          ) : (
            <ol className="grid grid-cols-1 gap-2 md:grid-cols-2 lg:grid-cols-3">
              {plan.tasks.map((task) => (
                <li
                  key={task.taskId}
                  className="rounded border border-edge-soft bg-panel-2 px-3 py-2"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-[11px] text-ink-faint">M{task.milestone}</span>
                    <Badge tone={task.status === 'done' ? 'ok' : 'neutral'}>
                      {task.status === 'done' ? '已完成' : task.status === 'in-progress' ? '进行中' : '待开始'}
                    </Badge>
                  </div>
                  <div className="mt-1 text-sm text-ink">{task.title}</div>
                </li>
              ))}
            </ol>
          )}
        </Card>
      </div>
    </div>
  )
}
