/** 教学工作台（IDE）相关的共享类型。设计文档 10.1 的四种工作模式。 */

export type WorkspaceMode =
  | 'coding'
  | 'debugging'
  | 'visual-learning'
  | 'architecture'

export const WORKSPACE_MODES: ReadonlyArray<{
  value: WorkspaceMode
  label: string
}> = [
  { value: 'coding', label: '编程' },
  { value: 'debugging', label: '调试' },
  { value: 'visual-learning', label: '实验' },
  { value: 'architecture', label: '架构' },
]
