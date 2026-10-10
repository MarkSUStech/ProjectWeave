import type { ReactNode } from 'react'

export function Card({
  title,
  actions,
  children,
  className = '',
}: {
  title?: ReactNode
  actions?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section
      className={`rounded-lg border border-edge bg-panel ${className}`}
    >
      {(title || actions) && (
        <header className="flex items-center justify-between border-b border-edge-soft px-4 py-2.5">
          <h3 className="text-sm font-semibold text-ink">{title}</h3>
          {actions}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  )
}
