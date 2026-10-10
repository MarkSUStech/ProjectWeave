/**
 * L1 标准组件：C++ 内存与指针关系图（P4.5b.1，D38）。
 *
 * 数据绑定 debug:latest —— 全部来自真实 LLDB 会话：
 * - 变量值/类型：DAP variables（真实暂停数据）；
 * - 指向关系：服务端白名单 evaluate 地址匹配验证（只有精确相等才画箭头）；
 * - 未解析地址 / 空指针 / 数据不可用 / 快照过期 各自显式状态，绝不虚构连线。
 *
 * 布局稳定：变量节点按名称排序固定网格位置，值变化不重排整图；
 * 尊重"减少动态效果"设置（关闭箭头动画）。
 */
import { useMemo } from 'react'
import { ReactFlow, Background, Controls, Handle, Position, MarkerType, type Edge, type Node, type NodeProps } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useDebugStore } from '../../stores/debugStore'
import { useUiReducedMotion } from '../../hooks/useUiReducedMotion'
import type { DebugScope, PointerGraph } from '../../api/debug'

type MemoryNodeData = {
  label: string
  varType: string | null
  value: string
  address: string | null
  state: 'normal' | 'nullPointer' | 'unresolved' | 'verifiedSource' | 'unavailable'
  changed: boolean
}

type MemoryNodeType = Node<MemoryNodeData, 'memory-var'>

function MemoryVarNode({ data }: NodeProps<MemoryNodeType>) {
  const stateStyle: Record<MemoryNodeData['state'], string> = {
    normal: 'border-edge-soft',
    nullPointer: 'border-danger/50',
    unresolved: 'border-warn/50',
    verifiedSource: 'border-accent/60',
    unavailable: 'border-ink-faint/40 border-dashed',
  }
  const stateBadge: Record<MemoryNodeData['state'], string | null> = {
    normal: null,
    nullPointer: '空指针',
    unresolved: '地址未解析',
    verifiedSource: null,
    unavailable: '数据不可用',
  }
  return (
    <div className={`min-w-36 rounded-md border-2 bg-panel px-2.5 py-1.5 font-mono text-[11px] ${stateStyle[data.state]}`}>
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-medium text-ink">{data.label}</span>
        {data.varType && <span className="text-[9px] text-ink-faint">{data.varType}</span>}
      </div>
      <div className={`mt-0.5 ${data.changed ? 'text-accent' : 'text-ink-dim'}`}>
        = {data.value}{data.changed && <span className="ml-1 text-[9px] text-accent">↻</span>}
      </div>
      {data.address && <div className="mt-0.5 text-[9px] text-ink-faint">@ {data.address}</div>}
      {stateBadge[data.state] && (
        <div className={`mt-0.5 text-[9px] ${data.state === 'nullPointer' ? 'text-danger' : 'text-warn'}`}>
          ⚠ {stateBadge[data.state]}
        </div>
      )}
    </div>
  )
}

const nodeTypes = { 'memory-var': MemoryVarNode }

/** 固定网格布局：按变量名排序分配位置（同帧内稳定；值变化不重排）。 */
function gridPosition(index: number) {
  const perRow = 3
  return { x: (index % perRow) * 230, y: Math.floor(index / perRow) * 110 }
}

interface GraphInput {
  scopes: DebugScope[]
  graph: PointerGraph | null
  changedNames: Set<string>
}

function buildGraphNodesEdges({ scopes, graph, changedNames }: GraphInput): { nodes: MemoryNodeType[]; edges: Edge[] } {
  const scope = scopes.find((s) => s.name === 'Locals') ?? scopes[0]
  if (!scope) return { nodes: [], edges: [] }
  const variables = scope.variables
  const addresses = graph?.addresses ?? {}
  const verified = new Set((graph?.verifiedEdges ?? []).map((e) => e.from))
  const nulls = new Set((graph?.nullPointers ?? []).map((e) => e.name))
  const unresolved = new Set((graph?.unresolvedPointers ?? []).map((e) => e.name))

  const sorted = [...variables].sort((a, b) => a.name.localeCompare(b.name))
  const nodes: MemoryNodeType[] = sorted.map((v, i) => {
    let state: MemoryNodeData['state'] = 'normal'
    if (nulls.has(v.name)) state = 'nullPointer'
    else if (unresolved.has(v.name)) state = 'unresolved'
    else if (verified.has(v.name)) state = 'verifiedSource'
    const address = addresses[v.name] ?? null
    return {
      id: v.name,
      type: 'memory-var',
      position: gridPosition(i),
      data: {
        label: v.name,
        varType: v.type,
        value: v.value,
        address,
        state,
        changed: changedNames.has(v.name),
      },
    }
  })

  // 仅已验证关系绘制确定性箭头（from → to）
  const edges: Edge[] = (graph?.verifiedEdges ?? []).map((edge, i) => ({
    id: `edge-${edge.from}-${i}`,
    source: edge.from,
    target: edge.to,
    label: edge.address.slice(-6),
    labelStyle: { fontSize: 9, fill: 'var(--color-ink-faint, #888)' },
    style: { stroke: 'var(--color-accent, #7c6cf0)', strokeWidth: 2 },
    markerEnd: { type: MarkerType.ArrowClosed, color: 'var(--color-accent, #7c6cf0)' },
  }))

  return { nodes, edges }
}

export function MemoryGraphView(_: { instanceId: string; config: Record<string, unknown> }) {
  const snapshot = useDebugStore((s) => s.snapshot)
  const frameVars = useDebugStore((s) => s.frameVars)
  const selectedFrameId = useDebugStore((s) => s.selectedFrameId)
  const reduced = useUiReducedMotion()

  // 变化标记：同帧同代次内按名称对比（不同帧/新代次重置——D38 数据隔离）
  const changedNames = useMemo(() => {
    const set = new Set<string>()
    const frameKey = selectedFrameId ?? 'top'
    const scope = selectedFrameId !== null
      ? frameVars[selectedFrameId]?.scopes.find((s) => s.name === 'Locals') ?? frameVars[selectedFrameId]?.scopes[0]
      : snapshot?.scopes.find((s) => s.name === 'Locals') ?? snapshot?.scopes[0]
    if (!scope) return set
    const key = `${frameKey}:${snapshot?.pauseSeq ?? 0}`
    const prev = changeHistory.get(key)
    if (prev) {
      for (const v of scope.variables) {
        const before = prev.get(v.name)
        if (before !== undefined && before !== v.value) set.add(v.name)
      }
    }
    const now = new Map(scope.variables.map((v) => [v.name, v.value]))
    changeHistory.set(key, now)
    // 只保留当前帧+代次的历史（递归帧同名变量不互相污染）
    for (const k of changeHistory.keys()) {
      if (k !== key) changeHistory.delete(k)
    }
    return set
  }, [snapshot?.pauseSeq, snapshot?.scopes, frameVars, selectedFrameId])

  const input = useMemo<GraphInput>(() => {
    if (selectedFrameId !== null && frameVars[selectedFrameId]) {
      return {
        scopes: frameVars[selectedFrameId].scopes,
        graph: frameVars[selectedFrameId].pointerGraph,
        changedNames,
      }
    }
    return { scopes: snapshot?.scopes ?? [], graph: snapshot?.pointerGraph ?? null, changedNames }
  }, [snapshot, frameVars, selectedFrameId, changedNames])

  const { nodes, edges } = useMemo(() => buildGraphNodesEdges(input), [input])

  if (!snapshot || snapshot.status === 'terminated') {
    return (
      <div className="flex h-full items-center justify-center p-4 text-center text-xs leading-relaxed text-ink-faint">
        启动调试并暂停后，这里以真实 LLDB 数据展示变量、地址与已验证的指针关系。
      </div>
    )
  }

  // 运行中：不把上一次暂停数据当作实时状态（验收 H）
  const running = snapshot.status !== 'paused'
  const frameLabel = selectedFrameId !== null ? `帧 #${selectedFrameId}` : '顶帧'

  return (
    <div className="relative h-full min-h-0">
      {running && (
        <div className="absolute inset-x-0 top-0 z-10 border-b border-accent/30 bg-accent-soft px-3 py-1 text-[11px] text-accent">
          ● 程序运行中——下图是第 {snapshot.pauseSeq} 次暂停的历史快照，非实时状态
        </div>
      )}
      {input.graph === null && !running && input.scopes.length > 0 && (
        <div className="absolute inset-x-0 top-0 z-10 border-b border-warn/30 bg-warn/10 px-3 py-1 text-[11px] text-warn">
          ⚠ 指针数据不可用（调试器未返回可靠地址；变量值为真实数据）
        </div>
      )}
      <div className="pointer-events-none absolute right-2 top-2 z-10 rounded border border-edge-soft bg-panel/90 px-2 py-1 text-[10px] text-ink-faint">
        <div>{frameLabel} · 暂停代次 #{snapshot.pauseSeq} · 真实 {snapshot.debuggerProfile}</div>
        <div>实线箭头 = 已验证指向；⚠ = 空指针/未解析</div>
      </div>
      {nodes.length === 0 ? (
        <div className="flex h-full items-center justify-center p-4 text-xs text-ink-faint">
          {input.graph === null && input.scopes.length > 0
            ? '指针数据不可用（调试器未返回可靠地址）'
            : '当前作用域暂无变量'}
        </div>
      ) : (
        <ReactFlow
          nodes={nodes}
          edges={edges.map((e) => (reduced ? e : { ...e, animated: true }))}
          nodeTypes={nodeTypes}
          fitView
          proOptions={{ hideAttribution: true }}
          nodesConnectable={false}
          edgesFocusable={false}
          minZoom={0.4}
        >
          <Background gap={20} />
          <Controls showInteractive={false} />
        </ReactFlow>
      )}
    </div>
  )
}

/** 帧内变化历史：键 = 帧:代次（换帧/新暂停即隔离，同名变量不串扰）。 */
const changeHistory = new Map<string, Map<string, string>>()
