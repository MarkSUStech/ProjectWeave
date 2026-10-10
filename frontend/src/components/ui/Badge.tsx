import type { ReactNode } from 'react'

type Tone = 'neutral' | 'info' | 'ok' | 'warn' | 'danger'

const TONE_CLASSES: Record<Tone, string> = {
  neutral: 'border-edge text-ink-dim bg-panel-2',
  info: 'border-accent/40 text-accent bg-accent-soft',
  ok: 'border-ok/40 text-ok bg-ok/10',
  warn: 'border-warn/40 text-warn bg-warn/10',
  danger: 'border-danger/40 text-danger bg-danger/10',
}

export function Badge({
  tone = 'neutral',
  children,
  className = '',
}: {
  tone?: Tone
  children: ReactNode
  className?: string
}) {
  return (
    <span
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-xs font-medium ${TONE_CLASSES[tone]} ${className}`}
    >
      {children}
    </span>
  )
}
