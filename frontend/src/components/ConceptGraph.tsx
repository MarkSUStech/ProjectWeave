import { useEffect, useState } from 'react'
import { ReactFlow, Background, Controls, MiniMap, Handle, Position, MarkerType, useNodesState, type Node, type NodeProps } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import type { Concept } from '../types/concept'
import type { Mastery } from '../types/mastery'
import { conceptEdges } from '../lib/conceptGraph'
import { ErrorBanner } from './ui/Feedback'
import { Button } from './ui/Button'
import { useAppearanceStore } from '../stores/appearanceStore'

type ConceptNodeType = Node<{ label: string; conceptId: string; domain: string; evidence: string }, 'concept'>

function ConceptNode({ data, selected }: NodeProps<ConceptNodeType>) {
  return <div className={`project-surface w-52 rounded-xl border bg-panel px-4 py-3 ${selected ? 'border-accent ring-2 ring-accent/20' : 'border-edge'}`}>
    <Handle type="target" position={Position.Left} />
    <div className="mb-1.5 text-[10px] text-accent">{data.domain}</div>
    <div className="text-xs font-semibold text-ink">{data.label}</div>
    <div className="mt-1 truncate font-mono text-[10px] text-ink-faint">{data.conceptId}</div>
    <div className="mt-2 text-[10px] text-ink-dim">{data.evidence}</div>
    <Handle type="source" position={Position.Right} />
  </div>
}
const nodeTypes = { concept: ConceptNode }

/** 概念图来自真实 API，ELK 自动排布；画布调整不写回知识库。 */
export default function ConceptGraph({ concepts, masteryByConcept, onSelect }: {
  concepts: Concept[]; masteryByConcept: Map<string, Mastery>; onSelect: (id: string) => void
}) {
  const p = useAppearanceStore((s) => s.preferences)
  const [nodes, setNodes, onNodesChange] = useNodesState<ConceptNodeType>([])
  const [error, setError] = useState<string | null>(null)
  const [revision, setRevision] = useState(0)
  const [loading, setLoading] = useState(true)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const selectedConcept = concepts.find((concept) => concept.id === selectedId)
  const edges = conceptEdges(concepts).map((edge) => ({ ...edge, markerEnd: { type: MarkerType.ArrowClosed }, style: { stroke: '#85808f' } }))
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    // 大体积 ELK 仅在用户进入图视图时下载。
    void import('elkjs/lib/elk.bundled.js').then(async ({ default: ELK }) => {
      const graph = await new ELK().layout({ id: 'knowledge', layoutOptions: {
        'elk.algorithm': 'layered', 'elk.direction': 'RIGHT', 'elk.spacing.nodeNode': '32', 'elk.layered.spacing.nodeNodeBetweenLayers': '70',
      }, children: concepts.map((c) => ({ id: c.id, width: 208, height: 116 })),
      edges: conceptEdges(concepts).map((edge) => ({ id: edge.id, sources: [edge.source], targets: [edge.target] })) })
      if (cancelled) return
      setNodes(concepts.map((c) => {
        const position = graph.children?.find((n) => n.id === c.id)
        const estimate = masteryByConcept.get(c.id)?.dimensions.understanding
        return { id: c.id, type: 'concept', position: { x: position?.x ?? 0, y: position?.y ?? 0 }, data: {
          label: c.title, conceptId: c.id, domain: c.domain,
          evidence: !estimate ? '尚无掌握证据' : estimate.confidence <= 0.5 ? `证据不足 · ${estimate.evidenceCount} 条` : `理解 ${Math.round(estimate.estimate * 100)}% · ${estimate.evidenceCount} 条证据`,
        } }
      }))
      setLoading(false)
    }).catch(() => { if (!cancelled) { setError('知识图布局失败，请重试。'); setLoading(false) } })
    return () => { cancelled = true }
  }, [concepts, masteryByConcept, setNodes, revision])
  return <div className="overflow-hidden rounded-xl border border-edge bg-panel">
    <div className="flex items-center justify-between border-b border-edge px-4 py-2.5">
      <div><h2 className="text-sm font-semibold">知识先修关系</h2><p className="mt-1 text-[11px] text-ink-dim">{concepts.length} 个概念 · 连线来自知识库 · 拖动节点，滚轮缩放，点击选择概念</p></div>
      <Button size="sm" variant="outline" onClick={() => setRevision((v) => v + 1)}>重新布局</Button>
    </div>
    {error && <ErrorBanner message={error} onRetry={() => setRevision((v) => v + 1)} />}
    <div className="relative h-[520px]" aria-label="交互式知识依赖图">
      {loading && <p role="status" className="absolute inset-0 z-10 grid place-items-center bg-panel text-xs text-ink-dim">正在计算知识图布局…</p>}
      {!loading && !error && <ReactFlow key={revision} nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange}
        onNodeClick={(_, node) => setSelectedId(node.id)} onSelectionChange={({ nodes: selected }) => setSelectedId(selected[0]?.id ?? null)} nodesConnectable={false} deleteKeyCode={null}
        fitView fitViewOptions={{ padding: 0.18 }} minZoom={0.2} maxZoom={1.8} colorMode={p.theme === 'paper' ? 'light' : 'dark'}
        ariaLabelConfig={{ 'controls.zoomIn.ariaLabel': '放大', 'controls.zoomOut.ariaLabel': '缩小', 'controls.fitView.ariaLabel': '适应画布', 'controls.interactive.ariaLabel': '切换画布交互' }}>
        <Background color="var(--color-edge)" gap={24} /><Controls /><MiniMap pannable zoomable nodeColor={p.accent} />
      </ReactFlow>}
    </div>
    {selectedConcept && <div className="flex items-center justify-between gap-4 border-t border-edge bg-panel-2 px-4 py-3" role="status">
      <div className="min-w-0"><div className="text-xs font-semibold">{selectedConcept.title}</div><p className="mt-1 text-xs text-ink-dim">{selectedConcept.description}</p></div>
      <Button size="sm" variant="outline" onClick={() => onSelect(selectedConcept.id)}>查看概念详情</Button>
    </div>}
  </div>
}
