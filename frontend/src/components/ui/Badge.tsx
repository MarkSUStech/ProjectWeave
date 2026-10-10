import type { ReactNode } from 'react'

type Tone = 'neutral' | 'info' | 'ok' | 'warn' | 'danger'

const TONE_CLASSES: Record<Tone, string> = {
  neutral: 'border-transparent text-ink-dim bg-panel-2',
  info: 'border-transparent text-accent bg-accent-soft',
  ok: 'border-transparent text-ok bg-ok/10',
  warn: 'border-transparent text-warn bg-warn/10',
  danger: 'border-transparent text-danger bg-danger/10',
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
      className={`inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-medium ${TONE_CLASSES[tone]} ${className}`}
    >
      {children}
    </span>
  )
}
