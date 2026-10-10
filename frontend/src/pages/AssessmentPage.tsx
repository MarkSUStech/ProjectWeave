import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  getAssessment,
  listProjectAssessments,
  startAssessment,
  submitAssessment,
} from '../api/assessments'
import { listConcepts } from '../api/concepts'
import { getProject } from '../api/projects'
import { ApiError } from '../api/client'
import type { AssessmentSession } from '../types/assessment'
import type { Project } from '../types/project'
import type { Concept } from '../types/concept'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { ErrorBanner, Spinner } from '../components/ui/Feedback'
import { formatDateTime } from '../lib/labels'

const LABEL_META: Record<string, { text: string; tone: 'ok' | 'warn' | 'danger' }> = {
  'likely-mastered': { text: '初步判断已掌握', tone: 'ok' },
  uncertain: { text: '尚不确定', tone: 'warn' },
  'likely-gap': { text: '疑似薄弱', tone: 'danger' },
}

function ResultsView({
  session,
  conceptTitles,
  onRestart,
}: {
  session: AssessmentSession
  conceptTitles: Map<string, Concept>
  onRestart: () => void
}) {
  const results = session.results!
  const counts = {
    mastered: results.concepts.filter((c) => c.label === 'likely-mastered').length,
    uncertain: results.concepts.filter((c) => c.label === 'uncertain').length,
    gap: results.concepts.filter((c) => c.label === 'likely-gap').length,
  }
  const itemById = new Map(session.items.map((item) => [item.itemId, item]))

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm">
          <span className="text-ink-dim">诊断完成 ·</span>
          <span className="text-ok">{counts.mastered} 已掌握</span>
          <span className="text-warn">{counts.uncertain} 不确定</span>
          <span className="text-danger">{counts.gap} 疑似薄弱</span>
          <span className="text-[11px] text-ink-faint">
            {session.completedAt ? formatDateTime(session.completedAt) : ''}
          </span>
        </div>
        <Button variant="outline" size="sm" onClick={onRestart}>
          重新诊断
        </Button>
      </div>

      <p className="rounded-md border border-edge-soft bg-panel/60 px-3 py-2 text-xs leading-relaxed text-ink-faint">
        结果为规则化初判（答对比例三档），置信度与学习证据模型在后续阶段（P2.3）接入；
        解释题与小编码任务诊断依赖 Tutor Engine，当前仅覆盖客观预测题。
      </p>

      <section className="rounded-lg border border-edge bg-panel">
        <h3 className="border-b border-edge-soft px-4 py-2.5 text-sm font-semibold">概念判断</h3>
        <ul>
          {results.concepts.map((concept) => {
            const meta = LABEL_META[concept.label]
            const conceptInfo = conceptTitles.get(concept.conceptId)
            return (
              <li
                key={concept.conceptId}
                className="flex items-center justify-between gap-3 border-b border-edge-soft px-4 py-2.5 last:border-b-0"
              >
                <div className="min-w-0">
                  <div className="truncate text-sm text-ink">
                    {conceptInfo?.title ?? concept.conceptId}
                  </div>
                  <div className="font-mono text-[11px] text-ink-faint">{concept.conceptId}</div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <span className="text-xs text-ink-faint">
                    {concept.correctCount}/{concept.total}
                  </span>
                  <Badge tone={meta.tone}>{meta.text}</Badge>
                </div>
              </li>
            )
          })}
        </ul>
      </section>

      <section className="rounded-lg border border-edge bg-panel">
        <h3 className="border-b border-edge-soft px-4 py-2.5 text-sm font-semibold">逐题回顾</h3>
        <ul className="divide-y divide-edge-soft">
          {results.questions.map((question, index) => {
            const item = itemById.get(question.itemId)
            return (
              <li key={question.itemId} className="px-4 py-3">
                <div className="mb-1 flex items-center justify-between gap-3">
                  <span className="text-xs text-ink-dim">
                    第 {index + 1} 题 · {question.conceptId}
                  </span>
                  <span className={question.correct ? 'text-xs text-ok' : 'text-xs text-danger'}>
                    {question.correct ? '✔ 回答正确' : '✘ 回答错误'}
                  </span>
                </div>
                {item && (
                  <>
                    <pre className="mb-2 whitespace-pre-wrap rounded bg-panel-2 px-3 py-2 font-mono text-[11px] leading-relaxed text-ink-dim">
                      {item.prompt}
                    </pre>
                    {!question.correct && (
                      <p className="text-xs text-ink-faint">
                        正确答案：{String.fromCharCode(65 + question.correctOptionIndex)}.{' '}
                        {item.options[question.correctOptionIndex]}
                      </p>
                    )}
                  </>
                )}
              </li>
            )
          })}
        </ul>
      </section>
    </div>
  )
}

function QuizView({
  session,
  submitting,
  error,
  onSubmit,
}: {
  session: AssessmentSession
  submitting: boolean
  error: string | null
  onSubmit: (answers: { itemId: string; selectedOptionIndex: number }[]) => void
}) {
  const [current, setCurrent] = useState(0)
  const [selections, setSelections] = useState<Record<string, number>>({})
  const item = session.items[current]
  const answeredCount = Object.keys(selections).length
  const allAnswered = answeredCount === session.items.length

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div className="flex items-center justify-between text-xs text-ink-faint">
        <span>
          第 {current + 1} / {session.items.length} 题 · {item.conceptId}
        </span>
        <span>
          已作答 {answeredCount}/{session.items.length}
        </span>
      </div>
      <div className="h-1 overflow-hidden rounded bg-panel-2">
        <div
          className="h-full bg-accent transition-all"
          style={{ width: `${(answeredCount / session.items.length) * 100}%` }}
        />
      </div>

      <section className="rounded-lg border border-edge bg-panel p-4">
        <pre className="whitespace-pre-wrap font-mono text-sm leading-relaxed text-ink">
          {item.prompt}
        </pre>
        <div className="mt-4 space-y-2">
          {item.options.map((option, index) => {
            const selected = selections[item.itemId] === index
            return (
              <button
                key={index}
                type="button"
                onClick={() => setSelections((s) => ({ ...s, [item.itemId]: index }))}
                className={`flex w-full items-start gap-2.5 rounded-md border px-3 py-2 text-left text-sm transition-colors ${
                  selected
                    ? 'border-accent bg-accent-soft text-ink'
                    : 'border-edge text-ink-dim hover:border-accent/40 hover:text-ink'
                }`}
              >
                <span className="mt-0.5 font-mono text-xs">
                  {String.fromCharCode(65 + index)}.
                </span>
                <span>{option}</span>
              </button>
            )
          })}
        </div>
      </section>

      {error && <ErrorBanner message={error} />}

      <div className="flex items-center justify-between">
        <Button
          variant="outline"
          disabled={current === 0}
          onClick={() => setCurrent((c) => c - 1)}
        >
          上一题
        </Button>
        {current < session.items.length - 1 ? (
          <Button variant="primary" onClick={() => setCurrent((c) => c + 1)}>
            下一题
          </Button>
        ) : (
          <Button
            disabled={!allAnswered || submitting}
            onClick={() =>
              onSubmit(
                Object.entries(selections).map(([itemId, selectedOptionIndex]) => ({
                  itemId,
                  selectedOptionIndex,
                })),
              )
            }
          >
            {submitting ? '提交中…' : allAnswered ? '提交诊断' : `还有 ${session.items.length - answeredCount} 题未作答`}
          </Button>
        )}
      </div>
    </div>
  )
}

/** 能力诊断页：按项目技术栈选题的规则化诊断（无 LLM 参与评分）。 */
export default function AssessmentPage() {
  const { id } = useParams<{ id: string }>()
  const [project, setProject] = useState<Project | null>(null)
  const [session, setSession] = useState<AssessmentSession | null>(null)
  const [conceptTitles, setConceptTitles] = useState<Map<string, Concept>>(new Map())
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [loading, setLoading] = useState(true)

  const initialize = useCallback(
    async (forceNew: boolean) => {
      if (!id) return
      setError(null)
      setSession(null)
      try {
        // 概念标题映射 + 项目信息（失败不阻塞主流程）
        listConcepts()
          .then((result) => setConceptTitles(new Map(result.items.map((c) => [c.id, c]))))
          .catch(() => undefined)
        getProject(id).then(setProject).catch(() => undefined)

        if (!forceNew) {
          const history = await listProjectAssessments(id)
          const latestCompleted = history.find((h) => h.status === 'completed')
          if (latestCompleted) {
            setSession(await getAssessment(latestCompleted.id))
            setLoading(false)
            return
          }
          const inProgress = history.find((h) => h.status === 'in-progress')
          if (inProgress) {
            setSession(await getAssessment(inProgress.id))
            setLoading(false)
            return
          }
        }
        setSession(await startAssessment(id))
      } catch (err) {
        setError(err instanceof ApiError ? err.message : '诊断初始化失败')
      } finally {
        setLoading(false)
      }
    },
    [id],
  )

  useEffect(() => {
    setLoading(true)
    void initialize(false)
  }, [initialize])

  const handleSubmit = useCallback(
    async (answers: { itemId: string; selectedOptionIndex: number }[]) => {
      if (!session) return
      setSubmitting(true)
      setError(null)
      try {
        setSession(await submitAssessment(session.id, answers))
      } catch (err) {
        setError(err instanceof ApiError ? err.message : '提交失败，请重试')
      } finally {
        setSubmitting(false)
      }
    },
    [session],
  )

  const view = useMemo(() => {
    if (loading) return <Spinner label="正在准备诊断…" />
    if (error && session === null) return <ErrorBanner message={error} onRetry={() => void initialize(false)} />
    if (session === null) return null
    if (session.status === 'completed' && session.results) {
      return (
        <ResultsView
          session={session}
          conceptTitles={conceptTitles}
          onRestart={() => void initialize(true)}
        />
      )
    }
    return (
      <QuizView session={session} submitting={submitting} error={error} onSubmit={(a) => void handleSubmit(a)} />
    )
  }, [loading, error, session, conceptTitles, submitting, initialize, handleSubmit])

  return (
    <div className="mx-auto min-h-full max-w-3xl px-6 py-10">
      <header className="mb-6">
        <Link
          to={id ? `/projects/${id}` : '/'}
          className="mb-3 inline-block text-sm text-ink-dim hover:text-ink"
        >
          ← 返回项目详情
        </Link>
        <h1 className="text-xl font-bold tracking-tight">能力诊断{project ? ` · ${project.title}` : ''}</h1>
        <p className="mt-1 text-xs leading-relaxed text-ink-faint">
          诊断范围由项目技术栈反推（设计原则：不做通用语言考试）；MVP
          为客观预测题与规则化判定，估计结果将用于后续课程规划。
        </p>
      </header>
      {view}
    </div>
  )
}
