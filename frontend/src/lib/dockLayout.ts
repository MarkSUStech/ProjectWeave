import type { AddPanelOptions, DockviewApi, SerializedDockview } from 'dockview-react'
import type { WorkspaceMode } from '../types/ide'

export const WORKSPACE_PANELS = [
  { id: 'files', title: '文件' }, { id: 'tasks', title: '任务' }, { id: 'history', title: '历史' },
  { id: 'editor', title: '编辑器' }, { id: 'canvas', title: '教学画布' }, { id: 'mentor', title: 'AI 导师' },
  { id: 'terminal', title: '终端' }, { id: 'tests', title: '测试' }, { id: 'events', title: '学习事件' },
] as const
export type WorkspacePanelId = typeof WORKSPACE_PANELS[number]['id']
export type DockPosition = 'left' | 'right' | 'above' | 'below' | 'within'
export const PANEL_TITLES = Object.fromEntries(WORKSPACE_PANELS.map((panel) => [panel.id, panel.title])) as Record<WorkspacePanelId, string>
export function isWorkspacePanel(id: string): id is WorkspacePanelId {
  return WORKSPACE_PANELS.some((panel) => panel.id === id)
}
export function panelOptions(id: WorkspacePanelId) {
  return { id, title: PANEL_TITLES[id], component: 'workspace', renderer: 'always',
    minimumWidth: id === 'editor' ? 260 : 170, minimumHeight: id === 'editor' ? 150 : 100 } satisfies AddPanelOptions
}

/** 工作模式只提供初始预设；之后每个项目/模式可独立自由布局。 */
export function buildDockPreset(api: DockviewApi, mode: WorkspaceMode) {
  api.clear()
  const main = mode === 'architecture' ? 'canvas' : 'editor'
  api.addPanel(panelOptions(main))
  api.addPanel({ ...panelOptions('files'), position: { referencePanel: main, direction: 'left' }, initialWidth: 230 })
  for (const id of ['tasks', 'history'] as const) api.addPanel({ ...panelOptions(id), position: { referencePanel: 'files', direction: 'within' }, inactive: true })
  if (mode !== 'architecture') {
    api.addPanel({ ...panelOptions('mentor'), position: { referencePanel: main, direction: 'right' }, initialWidth: 320 })
    if (mode !== 'coding') api.addPanel({ ...panelOptions('canvas'), position: { referencePanel: main, direction: 'below' }, initialHeight: mode === 'debugging' ? 210 : 370 })
  }
  api.addPanel({ ...panelOptions('terminal'), position: { direction: 'below' }, initialHeight: 190 })
  for (const id of ['tests', 'events'] as const) api.addPanel({ ...panelOptions(id), position: { referencePanel: 'terminal', direction: 'within' }, inactive: true })
  api.getPanel(main)?.api.setActive()
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
function dimension(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 100_000
}

/** 不信任 localStorage：只允许已注册面板、有限树结构和当前页内悬浮组。 */
export function validateDockLayout(value: unknown): value is SerializedDockview {
  if (!record(value) || !record(value.grid) || !record(value.panels)) return false
  if (!dimension(value.grid.width) || !dimension(value.grid.height)) return false
  if (value.grid.orientation !== 'HORIZONTAL' && value.grid.orientation !== 'VERTICAL') return false
  if (value.popoutGroups !== undefined && (!Array.isArray(value.popoutGroups) || value.popoutGroups.length > 0)) return false
  if (value.edgeGroups !== undefined) return false
  const ids = Object.keys(value.panels)
  if (ids.length > WORKSPACE_PANELS.length || ids.some((id) => !isWorkspacePanel(id))) return false
  for (const id of ids) {
    const panel = value.panels[id]
    if (!record(panel) || panel.id !== id || panel.contentComponent !== 'workspace') return false
  }
  const seen = new Set<string>()
  const groups = new Set<string>()
  const group = (data: unknown): boolean => {
    if (!record(data) || typeof data.id !== 'string' || groups.has(data.id) || !Array.isArray(data.views)) return false
    groups.add(data.id)
    for (const id of data.views) {
      if (typeof id !== 'string' || !ids.includes(id) || seen.has(id)) return false
      seen.add(id)
    }
    return data.activeView === undefined || (typeof data.activeView === 'string' && data.views.includes(data.activeView))
  }
  let nodes = 0
  const tree = (node: unknown, depth = 0): boolean => {
    if (++nodes > 40 || depth > 16 || !record(node) || (node.size !== undefined && !dimension(node.size))) return false
    if (node.type === 'leaf') return group(node.data)
    return node.type === 'branch' && Array.isArray(node.data) && node.data.every((child) => tree(child, depth + 1))
  }
  if (!tree(value.grid.root)) return false
  if (value.floatingGroups !== undefined) {
    if (!Array.isArray(value.floatingGroups) || value.floatingGroups.length > ids.length) return false
    for (const floating of value.floatingGroups) {
      if (!record(floating) || !record(floating.position)) return false
      if (Object.values(floating.position).some((n) => typeof n !== 'number' || !Number.isFinite(n) || Math.abs(n) > 100_000)) return false
      if (floating.grid !== undefined) {
        if (!record(floating.grid) || !tree(floating.grid.root)) return false
      } else if (!group(floating.data)) return false
    }
  }
  return seen.size === ids.length
}

export const dockLayoutKey = (projectId: string, mode: WorkspaceMode) => `pw-dock-layout-v1:${projectId}:${mode}`
export function readDockLayout(storage: Pick<Storage, 'getItem'>, projectId: string, mode: WorkspaceMode): SerializedDockview | null {
  const raw = storage.getItem(dockLayoutKey(projectId, mode))
  if (!raw) return null
  if (raw.length > 100_000) throw new Error('已保存的布局过大，已恢复默认布局。')
  const saved: unknown = JSON.parse(raw)
  if (!record(saved) || saved.version !== 1 || !validateDockLayout(saved.layout)) throw new Error('已保存的布局不兼容或损坏，已恢复默认布局。')
  return cleanDockLayout(saved.layout)
}

function cleanDockLayout(value: SerializedDockview): SerializedDockview {
  const layout = structuredClone(value)
  // 业务内容不进入布局持久化；恢复时不接受自定义组件或参数。
  for (const id of Object.keys(layout.panels)) if (isWorkspacePanel(id)) layout.panels[id] = {
    id, contentComponent: 'workspace', title: PANEL_TITLES[id], renderer: 'always',
    minimumWidth: id === 'editor' ? 260 : 170, minimumHeight: id === 'editor' ? 150 : 100,
  }
  return layout
}
export function writeDockLayout(storage: Pick<Storage, 'setItem'>, projectId: string, mode: WorkspaceMode, layout: SerializedDockview) {
  if (!validateDockLayout(layout)) throw new Error('当前布局无法保存，请恢复默认布局后重试。')
  storage.setItem(dockLayoutKey(projectId, mode), JSON.stringify({ version: 1, layout: cleanDockLayout(layout) }))
}
