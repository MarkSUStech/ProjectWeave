import { PlaceholderState } from '../ui/PlaceholderState'

/**
 * 中央区域的辅助画布占位（执行画布 / 教学画布 / 架构视图）。
 * Visual Interaction Engine（P3）将在此渲染绑定真实执行数据的
 * 交互式场景；当前仅作布局占位，不伪造任何执行结果。
 */
export function CanvasPlaceholder({
  kind,
  compact = false,
}: {
  kind: 'execution' | 'teaching' | 'architecture'
  compact?: boolean
}) {
  const meta = {
    execution: {
      title: '执行画布',
      phase: 'P3',
      description: '将显示与 codeVersion 绑定的真实执行状态（调用栈、变量、时间线）。',
    },
    teaching: {
      title: '教学画布',
      phase: 'P3',
      description: 'Visual Interaction Engine 将组合标准可视化组件（数组、栈帧、时间线等），数据来源会标注“真实执行 / 静态结构 / 概念模拟”。',
    },
    architecture: {
      title: '架构视图 · 未实现',
      phase: 'P3',
      description: '将基于静态分析展示模块依赖与项目结构图（React Flow），支持与源码双向定位。',
    },
  }[kind]

  return (
    <div className={`flex min-h-0 flex-col ${compact ? '' : 'flex-1'}`}>
      <div className="flex items-center justify-between border-y border-edge-soft bg-panel px-3 py-1.5">
        <span className="text-xs font-medium text-ink-dim">{meta.title}</span>
        <span className="rounded border border-edge px-1.5 py-0.5 font-mono text-[10px] text-ink-faint">
          {meta.phase}
        </span>
      </div>
      <div className={`min-h-0 ${compact ? 'flex-1' : 'flex-1'}`}>
        <PlaceholderState title={meta.title} phase={meta.phase} description={meta.description} />
      </div>
    </div>
  )
}
