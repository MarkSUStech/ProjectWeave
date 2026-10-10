import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { DockviewReact, themeDark, type DockviewApi, type DockviewReadyEvent, type IDockviewPanelProps, type IDockviewPanelHeaderProps, type IDockviewHeaderActionsProps } from 'dockview-react'
import 'dockview-react/dist/styles/dockview.css'
import { X, MoreHorizontal, Maximize2, Minimize2, AppWindow, ArrowLeft, ArrowRight, ArrowUp, ArrowDown, Layers } from 'lucide-react'
import { useIdeUiStore } from '../../stores/ideUiStore'
import type { WorkspaceMode } from '../../types/ide'
import { WORKSPACE_PANELS, PANEL_TITLES, isWorkspacePanel, buildDockPreset, panelOptions, readDockLayout, writeDockLayout, type WorkspacePanelId, type DockPosition } from '../../lib/dockLayout'
import { ErrorBanner } from '../ui/Feedback'
import { Button } from '../ui/Button'
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem, DropdownMenuSub, DropdownMenuSubTrigger, DropdownMenuSubContent, DropdownMenuSeparator, DropdownMenuLabel } from '../ui/upstream/dropdown-menu'
import { useWorkspaceLayout, useWorkspaceLayoutHost, type WorkspaceLayoutControls } from './WorkspaceLayoutContext'

const HostsContext = createContext<Partial<Record<WorkspacePanelId, HTMLDivElement>>>({})
const theme = { ...themeDark, name: 'projectweave', className: 'pw-dock-theme', gap: 1 }

/** 稳定 portal 宿主避免拖动、隐藏、模式切换卸载 Monaco 或导师草稿。 */
function DockContent({ api }: IDockviewPanelProps) {
  const hosts = useContext(HostsContext)
  const element = useRef<HTMLDivElement>(null)
  const host = isWorkspacePanel(api.id) ? hosts[api.id] : undefined
  useLayoutEffect(() => {
    const target = element.current
    if (!host || !target) return
    target.appendChild(host)
    return () => { if (host.parentElement === target) target.removeChild(host) }
  }, [host])
  return <div ref={element} className="h-full min-h-0" data-workspace-panel={api.id} />
}
const components = { workspace: DockContent }

function DockTab({ api }: IDockviewPanelHeaderProps) {
  const layout = useWorkspaceLayout()
  const locked = useIdeUiStore((s) => s.locked)
  return <div className="pw-dock-tab" title={locked ? '布局已锁定' : '拖动标题移动或合并面板'}>
    <span>{isWorkspacePanel(api.id) ? PANEL_TITLES[api.id] : api.title}</span>
    <button type="button" aria-label={`隐藏${api.title}`} disabled={locked} onPointerDown={(e) => e.stopPropagation()}
      onClick={(e) => { e.stopPropagation(); if (isWorkspacePanel(api.id)) layout?.hide(api.id) }} className="rounded p-0.5 text-ink-faint hover:bg-panel-2 hover:text-ink disabled:opacity-30"><X size={12} /></button>
  </div>
}

const POSITIONS: { position: DockPosition; label: string; icon: typeof ArrowLeft }[] = [
  { position: 'left', label: '移到工作区左侧', icon: ArrowLeft },
  { position: 'right', label: '移到工作区右侧', icon: ArrowRight },
  { position: 'above', label: '移到工作区顶部', icon: ArrowUp },
  { position: 'below', label: '移到工作区底部', icon: ArrowDown },
]

function DockActions({ activePanel, api }: IDockviewHeaderActionsProps) {
  const layout = useWorkspaceLayout()
  const locked = useIdeUiStore((s) => s.locked)
  const id = activePanel?.id
  if (!id || !isWorkspacePanel(id)) return null
  return <div className="flex h-full items-center gap-1 pr-2">
    <button type="button" disabled={locked || activePanel.group.api.location.type !== 'grid'} aria-label={api.isMaximized() ? '退出专注视图' : `专注${PANEL_TITLES[id]}`} onClick={() => layout?.maximize(id)} className="rounded p-1 text-ink-faint hover:bg-panel-2 hover:text-ink disabled:opacity-30">
      {api.isMaximized() ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
    </button>
    <DropdownMenu><DropdownMenuTrigger asChild><button type="button" aria-label={`${PANEL_TITLES[id]}面板菜单`} className="rounded p-1 text-ink-faint hover:bg-panel-2 hover:text-ink"><MoreHorizontal size={15} /></button></DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        <DropdownMenuLabel>{PANEL_TITLES[id]}{locked ? ' · 布局已锁定' : ''}</DropdownMenuLabel>
        {POSITIONS.map(({ position, label, icon: Icon }) => <DropdownMenuItem key={position} disabled={locked} onSelect={() => layout?.move(id, position)}><Icon />{label}</DropdownMenuItem>)}
        <DropdownMenuSub><DropdownMenuSubTrigger disabled={locked || (layout?.visible.length ?? 0) < 2}><Layers />与其他面板合并</DropdownMenuSubTrigger>
          <DropdownMenuSubContent>{layout?.visible.filter((other) => other !== id).map((other) => <DropdownMenuItem key={other} onSelect={() => layout.move(id, 'within', other)}>{PANEL_TITLES[other]}</DropdownMenuItem>)}</DropdownMenuSubContent>
        </DropdownMenuSub>
        <DropdownMenuItem disabled={locked} onSelect={() => layout?.float(id)}><AppWindow />在工作区内悬浮</DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem disabled={locked} onSelect={() => layout?.hide(id)}><X />隐藏面板</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  </div>
}

function EmptyDock() {
  const layout = useWorkspaceLayout()
  const locked = useIdeUiStore((s) => s.locked)
  return <div className="grid h-full place-items-center bg-app"><div className="space-y-4 text-center">
    <p className="text-sm text-ink-dim">所有面板已隐藏</p>
    <p className="text-xs text-ink-faint">从顶栏「视图」选择面板，或恢复当前模式的默认布局。</p>
    <Button variant="outline" disabled={locked} onClick={() => layout?.reset()}>恢复默认布局</Button>
  </div></div>
}

export function WorkspaceLayout({ mode, projectId, panels }: {
  mode: WorkspaceMode; projectId: string; panels: Record<WorkspacePanelId, ReactNode>
}) {
  const locked = useIdeUiStore((s) => s.locked)
  const { setControls } = useWorkspaceLayoutHost()
  const apiRef = useRef<DockviewApi | null>(null)
  const session = useRef({ mode, projectId, loading: false })
  const subscriptions = useRef<{ dispose: () => void }[]>([])
  const [error, setError] = useState<string | null>(null)
  const [hosts] = useState(() => Object.fromEntries(WORKSPACE_PANELS.map(({ id }) => {
    const host = document.createElement('div')
    host.className = 'h-full min-h-0 overflow-hidden'
    return [id, host]
  })) as Record<WorkspacePanelId, HTMLDivElement>)

  const guard = useCallback((action: (api: DockviewApi) => void) => {
    const api = apiRef.current
    if (!api || useIdeUiStore.getState().locked) return
    try { action(api) } catch { setError('布局调整失败，请恢复默认布局后重试。') }
  }, [])
  const persistLayout = useCallback(() => {
    const api = apiRef.current
    if (!api || session.current.loading) return
    try { writeDockLayout(localStorage, session.current.projectId, session.current.mode, api.toJSON()) }
    catch { setError('布局未能保存到浏览器；当前调整仍有效，刷新后可能无法恢复。') }
  }, [])
  const reset = useCallback(() => guard((api) => {
    session.current.loading = true
    try { buildDockPreset(api, session.current.mode); setError(null) }
    finally { session.current.loading = false }
    persistLayout()
  }), [guard, persistLayout])
  const actions = useRef<Omit<WorkspaceLayoutControls, 'visible' | 'active' | 'maximized' | 'canMaximize'> | null>(null)
  actions.current = {
    reveal: (id) => {
      const api = apiRef.current
      if (!api) return
      const panel = api.getPanel(id)
      if (panel) { panel.api.setActive(); return }
      guard((dock) => {
        const reference = id === 'tasks' || id === 'history' ? dock.getPanel('files') : id === 'tests' || id === 'events' ? dock.getPanel('terminal') : undefined
        dock.addPanel({ ...panelOptions(id), initialWidth: id === 'editor' ? 600 : id === 'files' ? 230 : 320, initialHeight: 190,
          position: reference ? { referencePanel: reference, direction: 'within' } : { direction: id === 'files' ? 'left' : id === 'terminal' || id === 'tests' || id === 'events' ? 'below' : 'right' } })
      })
    },
    hide: (id) => guard((api) => { const panel = api.getPanel(id); if (panel) api.removePanel(panel) }),
    move: (id, position, target) => guard((api) => {
      const panel = api.getPanel(id)
      const reference = target ? api.getPanel(target) : undefined
      if (!panel || (target && !reference) || target === id) return
      panel.api.exitMaximized()
      if (reference) panel.api.moveTo({ position: position === 'above' ? 'top' : position === 'below' ? 'bottom' : position === 'within' ? 'center' : position, group: reference.group })
      else if (position !== 'within') {
        const group = api.addGroup({ direction: position, initialWidth: Math.min(320, api.width * 0.25), initialHeight: Math.min(240, api.height * 0.3) })
        panel.api.moveTo({ group, position: 'center' })
      }
    }),
    float: (id) => guard((api) => {
      const panel = api.getPanel(id)
      if (!panel) return
      panel.api.exitMaximized()
      api.addFloatingGroup(panel, { x: 80, y: 60, width: Math.min(600, api.width - 80), height: Math.min(420, api.height - 60) })
    }),
    maximize: (id) => guard((api) => { const panel = api.getPanel(id); if (!panel || panel.group.api.location.type !== 'grid') return; if (panel.api.isMaximized()) panel.api.exitMaximized(); else panel.api.maximize() }),
    reset,
  }
  const syncControls = useCallback(() => {
    const api = apiRef.current
    if (!api || !actions.current) return
    const active = api.activePanel?.id
    setControls({ ...actions.current, visible: api.panels.map((panel) => panel.id).filter(isWorkspacePanel), active: active && isWorkspacePanel(active) ? active : null, maximized: api.activePanel?.api.isMaximized() ?? false, canMaximize: api.activePanel?.group.api.location.type === 'grid' })
  }, [setControls])
  const loadLayout = useCallback((api: DockviewApi, nextMode: WorkspaceMode, nextProject: string) => {
    session.current = { mode: nextMode, projectId: nextProject, loading: true }
    setError(null)
    try {
      const saved = readDockLayout(localStorage, nextProject, nextMode)
      if (saved) api.fromJSON(saved)
      else buildDockPreset(api, nextMode)
    } catch {
      buildDockPreset(api, nextMode)
      setError('已保存的布局无法恢复，已使用默认布局；项目文件与编辑草稿不受影响。')
    } finally { session.current.loading = false }
    syncControls()
  }, [syncControls])
  const onReady = useCallback(({ api }: DockviewReadyEvent) => {
    apiRef.current = api
    loadLayout(api, session.current.mode, session.current.projectId)
    subscriptions.current = [
      api.onDidLayoutChange(() => { syncControls(); persistLayout() }),
      api.onDidActivePanelChange(() => syncControls()),
      api.onDidMaximizedGroupChange(() => syncControls()),
      api.onWillDragPanel((event) => { if (useIdeUiStore.getState().locked) event.nativeEvent.preventDefault() }),
      api.onWillDragGroup((event) => { if (useIdeUiStore.getState().locked) event.nativeEvent.preventDefault() }),
      api.onWillDrop((event) => { if (useIdeUiStore.getState().locked) event.preventDefault() }),
    ]
  }, [loadLayout, syncControls, persistLayout])
  useEffect(() => {
    const api = apiRef.current
    if (api && (session.current.mode !== mode || session.current.projectId !== projectId)) {
      persistLayout()
      loadLayout(api, mode, projectId)
    }
  }, [mode, projectId, loadLayout, persistLayout])
  useEffect(() => () => {
    subscriptions.current.forEach((subscription) => subscription.dispose())
    apiRef.current = null
    setControls(null)
  }, [setControls])

  return <HostsContext.Provider value={hosts}>
    <div className="flex h-full min-h-0 flex-col overflow-clip" data-layout-locked={locked}>
      {error && <div className="shrink-0 p-2"><ErrorBanner message={error} onRetry={locked ? undefined : reset} /></div>}
      <DockviewReact className="min-h-0 flex-1 overflow-clip" components={components} defaultTabComponent={DockTab} rightHeaderActionsComponent={DockActions}
        watermarkComponent={EmptyDock} onReady={onReady} theme={theme} locked={locked} disableDnd={locked} dndStrategy="pointer"
        defaultRenderer="always" floatingGroupBounds="boundedWithinViewport" getTabContextMenuItems={() => []}
        onWillDrop={(event) => { if (useIdeUiStore.getState().locked) event.preventDefault() }}
        messages={{ closeTab: (title) => `隐藏${title}`, panelOpened: (title) => `已显示${title}`, panelClosed: (title) => `已隐藏${title}`, groupMaximized: (title) => `正在专注${title}`, groupRestored: (title) => `已退出${title}的专注视图`, groupFloated: (title) => `${title}已悬浮`, groupDocked: (title) => `${title}已停靠` }} />
    </div>
    {WORKSPACE_PANELS.map(({ id }) => createPortal(panels[id], hosts[id], id))}
  </HostsContext.Provider>
}
