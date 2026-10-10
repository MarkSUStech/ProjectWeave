import { useLayoutEffect, type ReactNode } from 'react'
import { MotionConfig } from 'motion/react'
import { useAppearanceStore } from '../../stores/appearanceStore'
import { applyAppearance } from '../../lib/appearance'

export function AppearanceProvider({ children }: { children: ReactNode }) {
  const { preferences, hydrate } = useAppearanceStore()
  useLayoutEffect(() => { hydrate() }, [hydrate])
  useLayoutEffect(() => { applyAppearance(preferences) }, [preferences])
  return <MotionConfig reducedMotion={preferences.motion ? 'user' : 'always'} transition={{ duration: preferences.motion ? 0.2 : 0, ease: [0.16, 1, 0.3, 1] }}>{children}</MotionConfig>
}
