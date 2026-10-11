/**
 * 课程生成页（P7.1）：输入 GitHub URL → 轮询进度 → 分析摘要 → 蓝图预览
 * （里程碑/任务/依赖图/证据/验证）→ 发布。全部数据来自真实后端记录。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  buildLessons,
  createCourseGeneration,
  getCourseAnalysis,
  getCourseBlueprint,
  getCourseGeneration,
  getRelease,
  instantiateRelease,
  publishCourseGeneration,
  retryCourseGeneration,
  STAGE_LABELS,
  TERMINAL_STATUSES,
  type CourseBlueprint,
  type CourseGeneration,
  type CourseRelease,
  type RepositoryAnalysis,
  type TaskSpec,
  type ValidationInfo,
} from '../api/courseGeneration'
import { ApiError } from '../api/client'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { ErrorBanner, Spinner } from '../components/ui/Feedback'

const KIND_BADGES: Record<string, { text: string; tone: 'ok' | 'warn' | 'neutral' }> = {
  confirmed: { text: '已证实', tone: 'ok' },
  inferred: { text: '推断', tone: 'warn' },
  unknown: { text: '未知', tone: 'neutral' },
}

export default function CourseGeneratePage() {
  const [url, setUrl] = useState('')
  const [gen, setGen] = useState<CourseGeneration | null>(null)
  const [analysis, setAnalysis] = useState<RepositoryAnalysis | null>(null)
  const [toolCalls, setToolCalls] = useState<Array<{ tool: string; ok: boolean }>>([])
  const [blueprint, setBlueprint] = useState<CourseBlueprint | null>(null)
  const [validation, setValidation] = useState<ValidationInfo | null>(null)
  const [selectedTask, setSelectedTask] = useState<TaskSpec | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [release, setRelease] = useState<CourseRelease | null>(null)
  const [busy, setBusy] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  const loadResults = useCallback(async (id: string) => {
    try {
      const [analysisData, blueprintData] = await Promise.all([
        getCourseAnalysis(id),
        getCourseBlueprint(id),
      ])
      setAnalysis(analysisData.analysis)
      setToolCalls(analysisData.toolCalls)
      setBlueprint(blueprintData.blueprint)
      setValidation(blueprintData.validation)
    } catch { /* 中间产物可能尚未生成 */ }
  }, [])

  useEffect(() => {
    if (!gen || TERMINAL_STATUSES.has(gen.status)) {
      stopPolling()
      if (gen && TERMINAL_STATUSES.has(gen.status)) void loadResults(gen.id)
      return
    }
    void loadResults(gen.id)
    pollRef.current = setInterval(() => {
      void getCourseGeneration(gen.id)
        .then((data) => setGen(data))
        .catch(() => undefined)
    }, 2000)
    return stopPolling
  }, [gen?.id, gen?.status]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => stopPolling, [stopPolling])

  // 课程内容生成轮询
  useEffect(() => {
    if (!release || TERMINAL_STATUSES.has(release.status)) return
    const timer = setInterval(() => {
      void getRelease(release.id).then((d) => setRelease(d)).catch(() => undefined)
    }, 3000)
    return () => clearInterval(timer)
  }, [release?.id, release?.status]) // eslint-disable-line react-hooks/exhaustive-deps

  const submit = useCallback(async () => {
    setError(null)
    setBusy(true)
    try {
      const { id } = await createCourseGeneration(url.trim())
      setGen(await getCourseGeneration(id))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }, [url])

  const publish = useCallback(async () => {
    if (!gen) return
    setBusy(true)
    try {
      await publishCourseGeneration(gen.id)
      setGen(await getCourseGeneration(gen.id))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }, [gen])

  const startBuildLessons = useCallback(async () => {
    if (!gen) return
    setBusy(true)
    try {
      setRelease(await buildLessons(gen.id))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }, [gen])

  const startLearning = useCallback(async () => {
    if (!release) return
    setBusy(true)
    try {
      const result = await instantiateRelease(release.id, `${release.courseTitle}（我的课程）`)
      navigate(`/projects/${result.projectId}/ide`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }, [release])

  const retry = useCallback(async () => {
    if (!gen) return
    setBusy(true)
    try {
      setGen(await retryCourseGeneration(gen.id))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }, [gen])

  const navigate = useNavigate()
  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <div className="mb-2 flex items-center justify-between">
        <h1 className="text-lg font-semibold text-ink">从 GitHub 生成课程</h1>
        <Link to="/" className="text-xs text-accent hover:underline">← 返回首页</Link>
      </div>
      <p className="mb-6 text-xs leading-relaxed text-ink-dim">
        输入公开 GitHub 仓库地址，AI 将分析真实代码与架构，生成"从零重建式"课程蓝图
        （里程碑 / 任务依赖图 / 知识需求 / 来源证据），经确定性验证后可发布为课程草稿。
      </p>

      {/* 输入 */}
      <div className="mb-6 flex gap-2">
        <input
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          placeholder="https://github.com/karpathy/micrograd"
          className="min-w-0 flex-1 rounded-md border border-edge-soft bg-panel px-3 py-2 font-mono text-xs text-ink placeholder:text-ink-faint/60"
          disabled={busy || (!!gen && !TERMINAL_STATUSES.has(gen.status))}
        />
        {!gen || TERMINAL_STATUSES.has(gen.status) ? (
          <Button size="sm" disabled={busy || !url.trim()} onClick={() => void submit()}>
            {busy ? '提交中…' : '开始生成'}
          </Button>
        ) : null}
      </div>
      {error && <ErrorBanner message={error} onRetry={() => setError(null)} />}

      {/* 进度 */}
      {gen && (
        <section className="mb-6 rounded-lg border border-edge-soft bg-panel-2 p-4">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm font-medium text-ink">
              {gen.repo_owner}/{gen.repo_name}
              {gen.commit_sha && <span className="ml-2 font-mono text-[10px] text-ink-faint">@{gen.commit_sha.slice(0, 10)}</span>}
            </span>
            <Badge tone={gen.status === 'failed' ? 'danger' : gen.status === 'draft' || gen.status === 'published' ? 'ok' : 'info'}>
              {STAGE_LABELS[gen.stage ?? gen.status] ?? gen.status}
            </Badge>
          </div>
          <div className="mb-2 h-1.5 overflow-hidden rounded bg-panel">
            <div className="h-full bg-accent transition-all" style={{ width: `${gen.progress}%` }} />
          </div>
          {!TERMINAL_STATUSES.has(gen.status) && (
            <p className="text-[11px] text-ink-faint">● {STAGE_LABELS[gen.stage ?? ''] ?? '处理中'}…（自动刷新）</p>
          )}
          {gen.status === 'failed' && (
            <div className="mt-2 space-y-2">
              <p role="alert" className="rounded border border-danger/40 bg-danger/10 px-2.5 py-2 text-xs text-danger">{gen.error}</p>
              <Button size="sm" variant="outline" disabled={busy} onClick={() => void retry()}>重试</Button>
            </div>
          )}
          {gen.warnings.length > 0 && (
            <ul className="mt-2 space-y-1">
              {gen.warnings.map((w, i) => <li key={i} className="text-[11px] text-warn">⚠ {w}</li>)}
            </ul>
          )}
        </section>
      )}

      {/* 分析 */}
      {analysis && (
        <section className="mb-6 rounded-lg border border-edge-soft p-4">
          <h2 className="mb-2 text-sm font-medium text-ink">仓库分析（真实工具调用）</h2>
          <p className="mb-3 text-xs leading-relaxed text-ink-dim">{analysis.summary}</p>
          <div className="mb-3 flex flex-wrap gap-1">
            {analysis.tech_stack.map((t) => <Badge key={t}>{t}</Badge>)}
          </div>
          {toolCalls.length > 0 && (
            <details className="mb-3">
              <summary className="cursor-pointer text-[11px] text-ink-faint">Agent 探索轨迹（{toolCalls.length} 次工具调用）</summary>
              <ul className="mt-1 space-y-0.5 font-mono text-[10px] text-ink-faint">
                {toolCalls.map((t, i) => (
                  <li key={i}>{t.ok ? '✓' : '✗'} {t.tool}</li>
                ))}
              </ul>
            </details>
          )}
          <div className="grid gap-2 sm:grid-cols-2">
            {[
              { title: '核心模块', claims: analysis.modules },
              { title: '对外行为', claims: analysis.behaviors },
            ].map(({ title, claims }) => (
              <div key={title}>
                <div className="mb-1 text-[11px] font-medium text-ink-faint">{title}</div>
                <ul className="space-y-1.5">
                  {claims.slice(0, 5).map((c, i) => (
                    <li key={i} className="text-xs leading-relaxed text-ink-dim">
                      <Badge tone={KIND_BADGES[c.kind]?.tone ?? 'neutral'}>{KIND_BADGES[c.kind]?.text ?? c.kind}</Badge>
                      {' '}{c.statement}
                      {c.sources[0] && <span className="ml-1 font-mono text-[10px] text-ink-faint">({c.sources[0].path})</span>}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* 蓝图 */}
      {blueprint && (
        <section className="mb-6 rounded-lg border border-edge-soft p-4">
          <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-medium text-ink">{blueprint.project.title}</h2>
            {validation && (
              <Badge tone={validation.passed ? 'ok' : 'danger'}>
                {validation.passed ? '验证通过' : `验证未过（${validation.issues.filter((i) => i.severity === 'error').length} 错误）`}
              </Badge>
            )}
          </div>
          <p className="mb-3 text-xs leading-relaxed text-ink-dim">{blueprint.project.description}</p>
          <div className="mb-3 grid gap-1 text-[11px] text-ink-faint sm:grid-cols-2">
            <div>最终成品：{blueprint.project.final_artifact || '—'}</div>
            <div>难度：{blueprint.project.difficulty} · 面向：{blueprint.project.target_level}</div>
          </div>

          {/* 验证问题 */}
          {validation && validation.issues.length > 0 && (
            <details className="mb-3 rounded border border-edge-soft/60 px-2.5 py-1.5">
              <summary className="cursor-pointer text-[11px] text-ink-faint">
                验证与警告（{validation.issues.length} 条）
              </summary>
              <ul className="mt-1 space-y-1">
                {validation.issues.map((issue, i) => (
                  <li key={i} className={`text-[11px] ${issue.severity === 'error' ? 'text-danger' : 'text-warn'}`}>
                    [{issue.severity}] {issue.message} {issue.path && <span className="font-mono">({issue.path})</span>}
                  </li>
                ))}
              </ul>
            </details>
          )}

          {/* 里程碑 */}
          <div className="mb-1 text-[11px] font-medium text-ink-faint">里程碑（{blueprint.milestones.length}）</div>
          <ol className="mb-4 space-y-2">
            {blueprint.milestones.map((ms, i) => (
              <li key={ms.milestoneId} className="rounded border border-edge-soft/70 px-3 py-2">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-xs font-medium text-ink">M{i + 1} · {ms.title}</span>
                  <span className="shrink-0 text-[10px] text-ink-faint">{ms.estimated_effort_band}</span>
                </div>
                <p className="mt-0.5 text-[11px] leading-relaxed text-ink-dim">{ms.description}</p>
                <div className="mt-1 text-[10px] text-ink-faint">
                  交付：{ms.deliverables.join('、')} · 验收：{ms.acceptance_criteria[0] ?? '—'}
                </div>
              </li>
            ))}
          </ol>

          {/* 任务列表（点击查看详情 + 证据） */}
          <div className="mb-1 text-[11px] font-medium text-ink-faint">任务（{blueprint.tasks.length}，点击查看详情与来源证据）</div>
          <ul className="mb-4 space-y-1">
            {blueprint.tasks.map((task) => (
              <li key={task.taskId}>
                <button
                  type="button"
                  onClick={() => setSelectedTask(selectedTask?.taskId === task.taskId ? null : task)}
                  className={`w-full rounded px-2 py-1.5 text-left text-xs transition-colors ${
                    selectedTask?.taskId === task.taskId ? 'bg-accent-soft text-ink' : 'text-ink-dim hover:bg-panel-2'
                  }`}
                >
                  <span className="font-mono text-[10px] text-ink-faint">{task.taskId}</span>{' '}
                  {task.title}
                  {task.depends_on.length > 0 && (
                    <span className="ml-2 font-mono text-[9px] text-ink-faint">← {task.depends_on.join(', ')}</span>
                  )}
                  {task.source_evidence.length === 0 && <span className="ml-1 text-[9px] text-warn">（无证据）</span>}
                </button>
              </li>
            ))}
          </ul>

          {/* 任务详情 */}
          {selectedTask && (
            <div className="rounded-lg border border-accent/40 bg-accent-soft/40 p-3 text-xs leading-relaxed">
              <div className="mb-1 font-medium text-ink">{selectedTask.title}</div>
              <p className="mb-2 text-ink-dim">{selectedTask.description}</p>
              <ul className="mb-2 space-y-0.5 text-[11px] text-ink-dim">
                {selectedTask.learning_objectives.length > 0 && <li>学习目标：{selectedTask.learning_objectives.join('；')}</li>}
                {selectedTask.deliverables.length > 0 && <li>交付：{selectedTask.deliverables.join('；')}</li>}
                {selectedTask.acceptance_criteria.length > 0 && <li>验收：{selectedTask.acceptance_criteria.join('；')}</li>}
                {selectedTask.test_strategy && <li>测试策略：{selectedTask.test_strategy}</li>}
                {selectedTask.required_concepts.length > 0 && <li>知识：{selectedTask.required_concepts.join('、')}</li>}
              </ul>
              {selectedTask.source_evidence.length > 0 && (
                <div className="mb-1 text-[10px] text-ink-faint">来源证据：</div>
              )}
              <ul className="space-y-0.5">
                {selectedTask.source_evidence.map((ev, i) => (
                  <li key={i} className="font-mono text-[10px] text-ink-faint">
                    📄 {ev.path}{ev.lines && `:${ev.lines}`} {ev.note && `— ${ev.note}`}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* 知识需求 */}
          {blueprint.knowledge_requirements.length > 0 && (
            <>
              <div className="mb-1 text-[11px] font-medium text-ink-faint">知识需求</div>
              <div className="flex flex-wrap gap-1">
                {blueprint.knowledge_requirements.map((k) => (
                  <Badge key={k.concept_id} tone={k.is_existing ? 'ok' : 'warn'}>
                    {k.title}{k.is_existing ? '' : '（候选）'}
                  </Badge>
                ))}
              </div>
            </>
          )}

          {/* 发布 */}
          <div className="mt-4 flex items-center gap-3 border-t border-edge-soft pt-3">
            {gen?.status === 'draft' && (
              <Button size="sm" disabled={busy || (validation?.passed === false)} onClick={() => void publish()}>
                发布课程草稿
              </Button>
            )}
            {gen?.status === 'published' && (
              <span className="text-xs text-ok">✔ 已发布（任务规格已持久化；教学代码与测试生成属 P7.2）</span>
            )}
            {gen?.status === 'failed' && (
              <Button size="sm" variant="outline" disabled={busy} onClick={() => void retry()}>重试生成</Button>
            )}
          </div>
        </section>
      )}

      {/* 课程内容生成（P7.2） */}
      {gen?.status === 'published' && !release && (
        <section className="mb-6 rounded-lg border border-edge-soft p-4">
          <h2 className="mb-1 text-sm font-medium text-ink">课程内容生产</h2>
          <p className="mb-3 text-xs leading-relaxed text-ink-dim">
            蓝图已发布。下一步：为每个任务生成初始代码、pytest 测试与参考实现，
            并在真实 Docker 沙箱中验证参考实现能通过全部测试（约 5-20 分钟）。
          </p>
          <Button size="sm" disabled={busy} onClick={() => void startBuildLessons()}>
            生成课程内容并验证
          </Button>
        </section>
      )}

      {release && (
        <section className="mb-6 rounded-lg border border-edge-soft p-4">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-medium text-ink">
              课程内容 · release v{release.releaseVersion}
            </h2>
            <Badge tone={release.status === 'ready' ? 'ok' : release.status === 'failed' ? 'danger' : 'info'}>
              {release.status === 'generating' ? '生成中' : release.status === 'verifying' ? `验证中${release.currentTask ? `（${release.currentTask}）` : ''}` : release.status === 'ready' ? '已就绪' : '失败'}
            </Badge>
          </div>
          <div className="mb-2 h-1.5 overflow-hidden rounded bg-panel">
            <div className="h-full bg-accent transition-all" style={{ width: `${release.progress}%` }} />
          </div>
          <div className="mb-3 text-[11px] text-ink-faint">
            任务 {release.passedTasks}/{release.totalTasks} 通过真实沙箱验证
            {release.failedTasks > 0 && <span className="text-danger">（{release.failedTasks} 失败）</span>}
          </div>
          {release.status === 'failed' && release.error && (
            <p role="alert" className="rounded border border-danger/40 bg-danger/10 px-2.5 py-2 text-xs text-danger">{release.error}</p>
          )}
          {release.status === 'ready' && (
            <div className="flex items-center gap-3">
              <Button size="sm" disabled={busy} onClick={() => void startLearning()}>
                开始学习（创建项目进入 IDE）
              </Button>
              <span className="text-[11px] text-ink-faint">
                将创建学习项目并进入教学 IDE（首任务初始代码 + 可运行测试）
              </span>
            </div>
          )}
        </section>
      )}

      {release && !TERMINAL_STATUSES.has(release.status) && (
        <div className="flex justify-center"><Spinner label="生成与验证课程内容（真实沙箱执行中，请勿关闭页面）…" /></div>
      )}

      {gen && !TERMINAL_STATUSES.has(gen.status) && (
        <div className="flex justify-center"><Spinner label="生成中（可能需要 1-3 分钟）…" /></div>
      )}
    </div>
  )
}
