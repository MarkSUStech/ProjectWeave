import type { ReactNode } from 'react'

/**
 * 未实现功能/空数据的统一占位组件。
 * 产品原则：宁可明确标注“未实现”，也不伪造功能。
 */
export function PlaceholderState({
  title,
  description,
  phase,
  children,
}: {
  title: string
  description: string
  /** 交付阶段标注，例如 “P1” */
  phase?: string
  children?: ReactNode
}) {
  return (
    <div className="flex h-full min-h-32 flex-col items-center justify-center gap-1.5 rounded-md border border-dashed border-edge bg-panel/50 p-6 text-center">
      <div className="flex items-center gap-2 text-sm font-medium text-ink-dim">
        {title}
        {phase && (
          <span className="rounded border border-edge px-1.5 py-0.5 font-mono text-[10px] text-ink-faint">
            {phase}
          </span>
        )}
      </div>
      <p className="max-w-sm text-xs leading-relaxed text-ink-faint">{description}</p>
      {children}
    </div>
  )
}

/** 数据为空（但功能已实现）时的空状态。 */
export function EmptyState({
  title,
  description,
  children,
}: {
  title: string
  description: string
  children?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-1.5 rounded-md border border-dashed border-edge-soft p-6 text-center">
      <div className="text-sm font-medium text-ink-dim">{title}</div>
      <p className="max-w-sm text-xs leading-relaxed text-ink-faint">{description}</p>
      {children}
    </div>
  )
}
