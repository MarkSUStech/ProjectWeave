import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { Badge } from '../ui/Badge'
import { listTutorDecisions, createTutorTurn } from '../../api/tutor'
import { ApiError } from '../../api/client'
import type { TutorDecision } from '../../types/tutor'
import {
  applyWorkspaceActions,
  confirmPatchAction,
  dismissPatchAction,
  type PatchApplyResult,
} from '../../lib/workspace/executor'

import { AnimatedGroup } from '../ui/upstream/animated-group'
import { AnimatePresence, motion } from 'motion/react'
import { Button } from '../ui/Button'
import { MessageSquare, Send } from 'lucide-react'
import { Dialog, DialogTrigger, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '../ui/upstream/dialog'
import { useUiReducedMotion } from '../../hooks/useUiReducedMotion'

const CodeDiff = lazy(() => import('./CodeDiff'))
type CurrentFile = { path: string; content: string }

const INTENT_LABELS: Record<string, string> = {
  question: '提问',
  hint: '提示',
  explain: '讲解',
  encourage: '鼓励',
  redirect: '调整方向',
}

function DecisionBubble({
  decision,
  currentFile,
  projectId,
  onApplyPatch,
}: {
  decision: TutorDecision
  currentFile?: CurrentFile
  projectId: string
  onApplyPatch: (path: string, content: string) => PatchApplyResult
}) {
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
        {decision.workspaceActions.filter((action) => action.kind === 'propose-patch').map((action, index) => {
          const path = String(action.payload.path ?? '')
          const content = action.payload.content
          if (typeof content !== 'string') return <p key={index} className="text-ink-faint">补丁提案只有说明，尚无可比较代码。</p>
          if (currentFile?.path !== path) return <p key={index} className="text-ink-faint">请打开「{path}」查看此提案的代码差异。</p>
          return <Dialog key={index}><DialogTrigger asChild><Button size="sm" variant="outline">查看代码提案差异</Button></DialogTrigger>
            <DialogContent className="sm:max-w-[min(1100px,90vw)]"><DialogHeader><DialogTitle>AI 代码提案 · {path}</DialogTitle><DialogDescription>左侧为当前草稿，右侧为服务端通过 Policy Gate 的提案。应用前请检查差异；应用后写入草稿并随自动保存保存（应用前内容进入历史快照）。文件未打开或有未保存更改时不会应用。</DialogDescription></DialogHeader>
              <div className="h-[min(60vh,600px)] overflow-hidden rounded-md border border-edge"><Suspense fallback={<p className="p-4">正在加载代码差异…</p>}><CodeDiff original={currentFile.content} modified={content} path={path} /></Suspense></div>
              <DialogFooter>
                <Button size="sm" variant="ghost" onClick={() => dismissPatchAction(projectId, action)}>拒绝</Button>
                <Button size="sm" onClick={() => confirmPatchAction(projectId, action, onApplyPatch)}>应用到编辑器草稿</Button>
              </DialogFooter>
            </DialogContent></Dialog>
        })}
        <p className="mt-1 text-[10px] text-ink-faint/70">
          {decision.model} · {decision.promptTokens + decision.completionTokens} tokens
        </p>
      </div>
    </div>
  )
}

/** AI Mentor 面板：教学回合（上下文组装 → LLM → Policy Gate 的真实调用）。 */
export function MentorPanel({
  projectId,
  currentFile,
  onApplyPatch,
  currentTaskId,
  recentRunResult,
}: {
  projectId: string
  currentFile?: CurrentFile
  /** A2 补丁应用回调（宿主提供，含未保存更改守卫）。 */
  onApplyPatch: (path: string, content: string) => PatchApplyResult
  /** 当前学习任务 ID（P4.1：随请求发送，让 Tutor 获得任务感知上下文）。 */
  currentTaskId?: string | null
  /** 最近一次运行/测试结果摘要。 */
  recentRunResult?: { status: string; summary: string } | null
}) {
  const reduced = useUiReducedMotion()
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
        extras: {
          currentTaskId: currentTaskId ?? undefined,
          currentCode: currentFile
            ? { path: currentFile.path, content: currentFile.content.slice(0, 2000) }
            : undefined,
          recentRunResult: recentRunResult ?? undefined,
        },
      })
      setQuestion('')
      setRequestAnswer(false)
      setUnconfigured(false)
      setDecisions((current) => [...(current ?? []), decision])
      // 新决策的工作台动作立即执行（A0 通知 / A1 布局切换×锁定联防 / A2 入确认队列）。
      // 历史决策不重放——页面加载时不重演旧的布局切换。
      applyWorkspaceActions(decision, projectId)
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
    <aside className="flex h-full min-h-0 flex-col bg-panel">
      <header className="flex h-12 shrink-0 items-center gap-2.5 border-b border-edge-soft px-4">
        <span className="grid size-7 place-items-center rounded-lg bg-accent-soft text-accent">
          <MessageSquare className="size-3.5" />
        </span>
        <div className="min-w-0">
          <div className="text-[13px] font-semibold">AI Mentor</div>
          <div className="mt-0.5 text-[10px] text-ink-faint">
            {unconfigured ? 'AI 未配置（后端 .env）' : '教学对话'}
          </div>
        </div>
      </header>

      <div ref={listRef} className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        {decisions === null && <p className="text-xs text-ink-faint">加载教学历史…</p>}
        {decisions !== null && decisions.length === 0 && (
          <div className="px-1 pb-6 pt-10">
          <MessageSquare className="mb-6 size-7 text-ink-faint" strokeWidth={1.25} />
          <h2 className="mb-3 text-base font-medium tracking-tight">一起把问题拆开</h2>
          <p className="text-[13px] leading-7 text-ink-dim">
            有问题随时问：AI 导师会结合你的学习路线、掌握状态与最近行为给提示——
            默认启发式提问，不直接代写代码。
          </p>
          </div>
        )}
        {decisions?.map((decision) => <AnimatedGroup key={decision.id} preset="fade"><DecisionBubble decision={decision} currentFile={currentFile} projectId={projectId} onApplyPatch={onApplyPatch} /></AnimatedGroup>)}
        <AnimatePresence>{sending && <motion.p role="status" initial={{ opacity: reduced ? 1 : 0 }} animate={{ opacity: 1 }} exit={{ opacity: reduced ? 1 : 0 }} transition={{ duration: reduced ? 0 : 0.2 }} className="text-xs text-accent">思考中…</motion.p>}</AnimatePresence>
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

      <footer className="space-y-3 p-4">
        <form onSubmit={send} className="flex items-center gap-2 rounded-xl border border-edge bg-app/70 p-2 focus-within:border-accent/60">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            disabled={sending}
            placeholder="问一个关于当前任务的问题…"
            className="min-w-0 flex-1 border-0 bg-transparent px-2 py-2 text-[13px] text-ink placeholder:text-ink-faint focus:outline-none disabled:opacity-50"
          />
          <Button size="sm" type="submit" disabled={!question.trim() || sending} aria-label="发送" className="size-8 shrink-0 rounded-lg p-0"><Send className="size-3.5" /></Button>
        </form>
        <label
          className="flex items-start gap-2 px-1 text-[11px] leading-5 text-ink-faint"
          title="勾选后允许 H4（答案级帮助）；系统会记录该请求，后续需要独立验证（设计 §8.3）"
        >
          <input
            type="checkbox"
            checked={requestAnswer}
            onChange={(e) => setRequestAnswer(e.target.checked)}
            className="mt-1 accent-warn"
          />
          请求答案级帮助（H4，将记录并需后续独立验证）
        </label>
      </footer>
    </aside>
  )
}
