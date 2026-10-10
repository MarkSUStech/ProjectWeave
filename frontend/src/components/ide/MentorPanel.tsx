import { useCallback, useEffect, useRef, useState } from 'react'
import { Badge } from '../ui/Badge'
import { listTutorDecisions, createTutorTurn } from '../../api/tutor'
import { ApiError } from '../../api/client'
import type { TutorDecision } from '../../types/tutor'

const INTENT_LABELS: Record<string, string> = {
  question: '提问',
  hint: '提示',
  explain: '讲解',
  encourage: '鼓励',
  redirect: '调整方向',
}

function DecisionBubble({ decision }: { decision: TutorDecision }) {
  return (
    <div className="space-y-1.5">
      <div className="ml-auto max-w-[95%] rounded-lg bg-accent-soft px-2.5 py-1.5 text-xs text-ink">
        {decision.question}
      </div>
      <div className="max-w-[95%] rounded-lg border border-edge-soft bg-panel-2 px-2.5 py-2 text-xs leading-relaxed text-ink-dim">
        <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
          <Badge tone="info">{INTENT_LABELS[decision.intent] ?? decision.intent}</Badge>
          <Badge>H{decision.hintLevel}</Badge>
          {decision.outcome === 'degraded' && <Badge tone="warn">已降级</Badge>}
          {decision.targetConcepts.map((concept) => (
            <span key={concept} className="font-mono text-[10px] text-ink-faint">
              {concept}
            </span>
          ))}
        </div>
        <p className="whitespace-pre-wrap">{decision.message}</p>
        <p className="mt-1 text-[10px] text-ink-faint/70">
          {decision.model} · {decision.promptTokens + decision.completionTokens} tokens
        </p>
      </div>
    </div>
  )
}

/** AI Mentor 面板：教学回合（上下文组装 → LLM → Policy Gate 的真实调用）。 */
export function MentorPanel({ projectId }: { projectId: string }) {
  const [decisions, setDecisions] = useState<TutorDecision[] | null>(null)
  const [unconfigured, setUnconfigured] = useState(false)
  const [question, setQuestion] = useState('')
  const [requestAnswer, setRequestAnswer] = useState(false)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const listRef = useRef<HTMLDivElement>(null)

  const loadHistory = useCallback(async () => {
    try {
      setDecisions(await listTutorDecisions(projectId, 10))
    } catch {
      setDecisions([])
    }
  }, [projectId])

  useEffect(() => {
    setDecisions(null)
    setUnconfigured(false)
    void loadHistory()
  }, [loadHistory])

  useEffect(() => {
    const list = listRef.current
    if (list) list.scrollTop = list.scrollHeight
  }, [decisions])

  const send = async (event: React.FormEvent) => {
    event.preventDefault()
    const trimmed = question.trim()
    if (!trimmed || sending) return
    setSending(true)
    setError(null)
    try {
      const decision = await createTutorTurn(projectId, trimmed, {
        requestAnswerLevel: requestAnswer,
      })
      setQuestion('')
      setRequestAnswer(false)
      setUnconfigured(false)
      setDecisions((current) => [...(current ?? []), decision])
    } catch (err) {
      if (err instanceof ApiError && err.status === 503) {
        setUnconfigured(true)
      } else {
        setError(err instanceof ApiError ? err.message : '发送失败，请重试')
      }
    } finally {
      setSending(false)
    }
  }

  return (
    <aside className="flex min-h-0 flex-col border-l border-edge bg-panel">
      <header className="flex items-center gap-2 border-b border-edge-soft px-3 py-2">
        <span className="grid size-6 place-items-center rounded bg-accent-soft font-mono text-xs text-accent">
          AI
        </span>
        <div className="min-w-0">
          <div className="text-xs font-semibold">AI Mentor</div>
          <div className="flex items-center gap-1.5 text-[11px] text-ink-faint">
            <span
              className={`size-1.5 rounded-full ${unconfigured ? 'bg-warn' : 'bg-ok'}`}
            />
            {unconfigured ? 'AI 未配置（后端 .env）' : 'Tutor Engine · Policy Gate'}
          </div>
        </div>
      </header>

      <div ref={listRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        {decisions === null && <p className="text-xs text-ink-faint">加载教学历史…</p>}
        {decisions !== null && decisions.length === 0 && (
          <p className="text-xs leading-relaxed text-ink-faint">
            有问题随时问：AI 导师会结合你的学习路线、掌握状态与最近行为给提示——
            默认启发式提问，不直接代写代码。
          </p>
        )}
        {decisions?.map((decision) => <DecisionBubble key={decision.id} decision={decision} />)}
        {sending && <p className="text-xs text-accent">思考中…</p>}
        {error && (
          <p role="alert" className="rounded border border-danger/40 bg-danger/10 px-2 py-1.5 text-xs text-danger">
            {error}
          </p>
        )}
        {unconfigured && (
          <p className="rounded border border-warn/40 bg-warn/10 px-2 py-1.5 text-xs text-warn">
            AI 未配置：在后端 .env 设置 PW_AI_PROVIDER=deepseek 与 PW_DEEPSEEK_API_KEY 后重启。
          </p>
        )}
      </div>

      <footer className="space-y-2 border-t border-edge-soft p-3">
        <label
          className="flex items-center gap-1.5 text-[11px] text-ink-faint"
          title="勾选后允许 H4（答案级帮助）；系统会记录该请求，后续需要独立验证（设计 §8.3）"
        >
          <input
            type="checkbox"
            checked={requestAnswer}
            onChange={(e) => setRequestAnswer(e.target.checked)}
            className="accent-warn"
          />
          请求答案级帮助（H4，将记录并需后续独立验证）
        </label>
        <form onSubmit={send} className="flex gap-2">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            disabled={sending}
            placeholder="问一个关于当前任务的问题…"
            className="min-w-0 flex-1 rounded-md border border-edge bg-panel-2 px-3 py-2 text-xs text-ink placeholder:text-ink-faint focus:border-accent/60 focus:outline-none disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={!question.trim() || sending}
            className="shrink-0 rounded-md bg-accent px-3 text-xs font-medium text-white disabled:opacity-50"
          >
            发送
          </button>
        </form>
      </footer>
    </aside>
  )
}
