import { createContext, useContext, useState, type ReactNode } from 'react'
import type { DockPosition, WorkspacePanelId } from '../../lib/dockLayout'

export interface WorkspaceLayoutControls {
  visible: WorkspacePanelId[]
  active: WorkspacePanelId | null
  maximized: boolean
  canMaximize: boolean
  reveal: (id: WorkspacePanelId) => void
  hide: (id: WorkspacePanelId) => void
  move: (id: WorkspacePanelId, position: DockPosition, target?: WorkspacePanelId) => void
  float: (id: WorkspacePanelId) => void
  maximize: (id: WorkspacePanelId) => void
  reset: () => void
}
const LayoutContext = createContext<{
  controls: WorkspaceLayoutControls | null
  setControls: (controls: WorkspaceLayoutControls | null) => void
} | null>(null)

export function WorkspaceLayoutProvider({ children }: { children: ReactNode }) {
  const [controls, setControls] = useState<WorkspaceLayoutControls | null>(null)
  return <LayoutContext.Provider value={{ controls, setControls }}>{children}</LayoutContext.Provider>
}
export function useWorkspaceLayout() { return useContext(LayoutContext)?.controls ?? null }
export function useWorkspaceLayoutHost() {
  const context = useContext(LayoutContext)
  if (!context) throw new Error('WorkspaceLayout 必须位于 WorkspaceLayoutProvider 内')
  return context
}
