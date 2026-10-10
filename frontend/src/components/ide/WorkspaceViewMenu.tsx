import { Columns3, Maximize2, Minimize2, RotateCcw } from 'lucide-react'
import { useIdeUiStore } from '../../stores/ideUiStore'
import { WORKSPACE_PANELS } from '../../lib/dockLayout'
import { Button } from '../ui/Button'
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuLabel, DropdownMenuCheckboxItem, DropdownMenuSeparator, DropdownMenuItem } from '../ui/upstream/dropdown-menu'
import { useWorkspaceLayout } from './WorkspaceLayoutContext'

/** 始终可达的面板恢复入口，包括全部面板隐藏后的空工作区。 */
export function WorkspaceViewMenu() {
  const layout = useWorkspaceLayout()
  const locked = useIdeUiStore((s) => s.locked)
  return <DropdownMenu>
    <DropdownMenuTrigger asChild><Button size="sm" variant="outline" aria-label="视图与面板" disabled={!layout}><Columns3 className="size-3.5" />视图</Button></DropdownMenuTrigger>
    <DropdownMenuContent align="end" className="w-56">
      <DropdownMenuLabel>{locked ? '布局已锁定，解锁后可调整' : '显示的面板'}</DropdownMenuLabel>
      {WORKSPACE_PANELS.map(({ id, title }) => <DropdownMenuCheckboxItem key={id} disabled={locked} checked={layout?.visible.includes(id)}
        onSelect={(event) => event.preventDefault()} onCheckedChange={(checked) => checked ? layout?.reveal(id) : layout?.hide(id)}>{title}</DropdownMenuCheckboxItem>)}
      <DropdownMenuSeparator />
      <DropdownMenuItem disabled={locked || !layout?.canMaximize} onSelect={() => { if (layout?.active) layout.maximize(layout.active) }}>
        {layout?.maximized ? <Minimize2 /> : <Maximize2 />}{layout?.maximized ? '退出专注视图' : '专注当前面板'}
      </DropdownMenuItem>
      <DropdownMenuItem disabled={locked} onSelect={() => layout?.reset()}><RotateCcw />恢复当前模式默认布局</DropdownMenuItem>
      <DropdownMenuSeparator />
      <p className="px-2 py-1.5 text-[11px] leading-5 text-ink-faint">拖动面板标题到边缘拆分，到中央合并。面板菜单支持移动与悬浮。</p>
    </DropdownMenuContent>
  </DropdownMenu>
}
