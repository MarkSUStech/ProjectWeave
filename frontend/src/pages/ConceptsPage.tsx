import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { listConcepts } from '../api/concepts'
import { listMastery } from '../api/mastery'
import { ApiError } from '../api/client'
import type { Concept } from '../types/concept'
import type { DimensionEstimate, Mastery } from '../types/mastery'
import { Badge } from '../components/ui/Badge'
import { ErrorBanner, Spinner } from '../components/ui/Feedback'
import { EmptyState } from '../components/ui/PlaceholderState'

const DOMAIN_LABELS: Record<string, string> = {
  javascript: 'JavaScript',
  typescript: 'TypeScript',
  browser: '浏览器',
  engineering: '工程实践',
}

const ASSESSMENT_LABELS: Record<string, string> = {
  prediction: '预测题',
  explanation: '解释题',
  coding: '独立编码',
  debugging: '调试',
  transfer: '迁移任务',
}

/** 理解维掌握徽标：证据不足（<2 条，confidence≤0.5）显示"尚不确定"（设计 6.2）。 */
function MasteryBadge({ understanding }: { understanding?: DimensionEstimate }) {
  if (!understanding) return null
  if (understanding.confidence <= 0.5) {
    return <Badge>尚不确定（{understanding.evidenceCount} 条证据）</Badge>
  }
  const tone = understanding.estimate >= 0.75 ? 'ok' : understanding.estimate >= 0.5 ? 'warn' : 'danger'
  return (
    <Badge tone={tone}>
      理解 {Math.round(understanding.estimate * 100)}%（{understanding.evidenceCount} 条证据）
    </Badge>
  )
}

function ConceptCard({
  concept,
  expanded,
  onToggle,
  mastery,
}: {
  concept: Concept
  expanded: boolean
  onToggle: () => void
  mastery?: Mastery
}) {
  return (
    <div className="rounded-lg border border-edge bg-panel">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full flex-col items-start gap-1 px-4 py-3 text-left"
      >
        <div className="flex w-full items-center justify-between gap-2">
          <span className="font-medium text-ink">{concept.title}</span>
          <span className="shrink-0 text-[11px] text-ink-faint">{expanded ? '收起 ▴' : '展开 ▾'}</span>
        </div>
        <span className="font-mono text-[11px] text-ink-faint">{concept.id}</span>
        <p className="text-xs leading-relaxed text-ink-dim">{concept.description}</p>
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          <MasteryBadge understanding={mastery?.dimensions.understanding} />
          {concept.prerequisites.length > 0 ? (
            concept.prerequisites.map((prerequisite) => (
              <Badge key={prerequisite}>先修 {prerequisite}</Badge>
            ))
          ) : (
            <Badge tone="ok">无先修 · 入口概念</Badge>
          )}
        </div>
      </button>
      {expanded && (
        <div className="space-y-2.5 border-t border-edge-soft px-4 py-3 text-xs">
          <div>
            <div className="mb-1 font-medium text-ink-dim">学习目标</div>
            <ul className="space-y-1">
              {concept.objectives.map((objective) => (
                <li key={objective} className="text-ink-dim">· {objective}</li>
              ))}
            </ul>
          </div>
          <div>
            <div className="mb-1 font-medium text-ink-dim">评估方式</div>
            <div className="flex flex-wrap gap-1.5">
              {concept.assessmentMethods.map((method) => (
                <Badge key={method} tone="info">
                  {ASSESSMENT_LABELS[method] ?? method}
                </Badge>
              ))}
            </div>
          </div>
          {concept.examples.length > 0 && (
            <div>
              <div className="mb-1 font-medium text-ink-dim">示例</div>
              <ul className="space-y-1">
                {concept.examples.map((example) => (
                  <li key={example} className="font-mono text-[11px] text-ink-faint">
                    {example}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/** 知识图谱浏览页：全局知识库预览 + 当前用户掌握估计叠加。 */
export default function ConceptsPage() {
  const [concepts, setConcepts] = useState<Concept[] | null>(null)
  const [domains, setDomains] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [masteryByConcept, setMasteryByConcept] = useState<Map<string, Mastery>>(new Map())

  const load = useCallback(async () => {
    setError(null)
    try {
      const result = await listConcepts()
      setConcepts(result.items)
      setDomains(result.domains)
    } catch (err) {
      setConcepts([])
      setError(err instanceof ApiError ? err.message : '未知错误')
    }
    // 掌握数据是叠加信息：加载失败不影响概念列表（未诊断时为空）。
    listMastery()
      .then((items) => setMasteryByConcept(new Map(items.map((m) => [m.conceptId, m]))))
      .catch(() => setMasteryByConcept(new Map()))
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const grouped = useMemo(() => {
    const map = new Map<string, Concept[]>()
    for (const domain of domains) map.set(domain, [])
    for (const concept of concepts ?? []) {
      if (!map.has(concept.domain)) map.set(concept.domain, [])
      map.get(concept.domain)!.push(concept)
    }
    return map
  }, [concepts, domains])

  return (
    <div className="mx-auto min-h-full max-w-5xl px-6 py-10">
      <header className="mb-6">
        <Link to="/" className="mb-3 inline-block text-sm text-ink-dim hover:text-ink">
          ← 返回项目列表
        </Link>
        <h1 className="text-xl font-bold tracking-tight">知识图谱</h1>
        <p className="mt-1 text-xs leading-relaxed text-ink-faint">
          系统的可测量知识单元与先修关系（当前 {concepts?.length ?? '…'} 个概念）。
          能力诊断（P2.2）与课程规划（P2.4）将基于这张图工作；此处为全局知识库预览。
        </p>
      </header>

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}
      {!error && concepts === null && <Spinner label="正在加载知识图谱…" />}
      {!error && concepts !== null && concepts.length === 0 && (
        <EmptyState
          title="知识库为空"
          description="知识概念由后端在启动时种子写入；请确认后端服务已启动并完成迁移。"
        />
      )}

      <div className="space-y-6">
        {[...grouped.entries()].map(([domain, items]) => (
          <section key={domain}>
            <h2 className="mb-2.5 flex items-center gap-2 text-sm font-semibold text-ink-dim">
              {DOMAIN_LABELS[domain] ?? domain}
              <span className="text-[11px] font-normal text-ink-faint">{items.length} 个概念</span>
            </h2>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {items.map((concept) => (
                <ConceptCard
                  key={concept.id}
                  concept={concept}
                  expanded={expandedId === concept.id}
                  onToggle={() =>
                    setExpandedId((current) => (current === concept.id ? null : concept.id))
                  }
                  mastery={masteryByConcept.get(concept.id)}
                />
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}
