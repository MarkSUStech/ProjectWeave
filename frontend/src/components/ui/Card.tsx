import type { ReactNode } from 'react'
import { Card as ShadcnCard, CardHeader, CardContent, CardTitle, CardAction } from './upstream/card'

export function Card({ title, actions, children, className = '' }: {
  title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string
}) {
  return (
    <ShadcnCard className={`project-surface gap-0 rounded-xl border-edge-soft bg-panel py-0 text-ink ${className}`}>
      {(title || actions) && <CardHeader className="items-center border-b border-edge-soft px-5 py-4">
        <CardTitle className="text-sm">{title}</CardTitle>
        {actions && <CardAction>{actions}</CardAction>}
      </CardHeader>}
      <CardContent className="p-5">{children}</CardContent>
    </ShadcnCard>
  )
}
