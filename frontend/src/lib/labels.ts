/** 领域枚举的中文显示与时间格式化。 */

import type { ProjectComplexity, ProjectMode, ProjectStatus } from '../types/project'

export const MODE_LABELS: Record<ProjectMode, string> = {
  rebuild: '从零重建',
  contribution: '开源贡献',
}

export const STATUS_LABELS: Record<ProjectStatus, string> = {
  draft: '草稿',
  analyzing: '分析中',
  active: '进行中',
  completed: '已完成',
  archived: '已归档',
}

export const COMPLEXITY_LABELS: Record<ProjectComplexity, string> = {
  small: '小',
  medium: '中',
  large: '大',
}

export function formatDateTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** 终端时间戳：只显示时:分:秒。 */
export function formatClock(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleTimeString('zh-CN', { hour12: false })
}
