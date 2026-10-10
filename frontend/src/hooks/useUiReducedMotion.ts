import { useReducedMotion } from 'motion/react'
import { useAppearanceStore } from '../stores/appearanceStore'

/** 用户关闭动效与系统减少动态效果共同约束动画。 */
export function useUiReducedMotion() {
  const system = useReducedMotion()
  const enabled = useAppearanceStore((s) => s.preferences.motion)
  return !!system || !enabled
}
