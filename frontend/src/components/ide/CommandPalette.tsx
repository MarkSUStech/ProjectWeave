import { useEffect, useState } from 'react'
import { Search, FileCode2, Save, Play, LayoutPanelLeft, LockKeyhole } from 'lucide-react'
import { CommandDialog, CommandInput, CommandList, CommandEmpty, CommandGroup, CommandItem, CommandShortcut } from '../ui/upstream/command'
import { Button } from '../ui/Button'
import { useIdeUiStore } from '../../stores/ideUiStore'
import { WORKSPACE_MODES } from '../../types/ide'
import type { FileMeta } from '../../types/file'
import { WORKSPACE_PANELS } from '../../lib/dockLayout'
import { useWorkspaceLayout } from './WorkspaceLayoutContext'
import { useAppearanceStore } from '../../stores/appearanceStore'

export function CommandPalette({ files, onOpenFile, onSave, onRun, canSave, canRun }: {
  files: FileMeta[] | null; onOpenFile: (path: string) => void; onSave: () => void; onRun: () => void; canSave: boolean; canRun: boolean
}) {
  const [open, setOpen] = useState(false)
  const layout = useWorkspaceLayout()
  const { setMode, locked, toggleLock } = useIdeUiStore()
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); if (!useAppearanceStore.getState().open) setOpen((v) => !v) }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])
  const run = (action: () => void) => { setOpen(false); action() }
  return <>
    <Button size="sm" variant="outline" className="gap-3 text-ink-faint" onClick={() => setOpen(true)} aria-label="打开命令面板"><Search className="size-3.5" /><span className="hidden xl:inline">命令</span><kbd className="rounded border border-edge-soft px-1 text-[10px] text-ink-faint">Ctrl K</kbd></Button>
    <CommandDialog open={open} onOpenChange={setOpen} title="工作台命令" description="搜索文件或操作，使用方向键选择，Enter 执行。" showCloseButton={false}>
      <CommandInput placeholder="搜索文件或命令…" />
      <CommandList>
        <CommandEmpty>没有匹配的文件或命令</CommandEmpty>
        <CommandGroup heading="工作台">
          <CommandItem onSelect={() => run(() => useAppearanceStore.getState().setOpen(true))}><LayoutPanelLeft />打开界面设置</CommandItem>
          <CommandItem disabled={!canSave} onSelect={() => run(onSave)}><Save />保存当前文件<CommandShortcut>Ctrl S</CommandShortcut></CommandItem>
          <CommandItem disabled={!canRun} onSelect={() => run(onRun)}><Play />运行当前文件 / 测试<CommandShortcut>Ctrl Enter</CommandShortcut></CommandItem>
          <CommandItem onSelect={() => run(toggleLock)}><LockKeyhole />{locked ? '解锁布局' : '锁定布局'}</CommandItem>
          {WORKSPACE_MODES.map((mode) => <CommandItem key={mode.value} disabled={locked} onSelect={() => run(() => setMode(mode.value))}><LayoutPanelLeft />切换到{mode.label}模式</CommandItem>)}
        </CommandGroup>
        {layout && <CommandGroup heading="视图与面板">
          {WORKSPACE_PANELS.map(({ id, title }) => <CommandItem key={id} disabled={locked} onSelect={() => run(() => layout.reveal(id))}><LayoutPanelLeft />显示{title}</CommandItem>)}
          <CommandItem disabled={locked} onSelect={() => run(layout.reset)}><LayoutPanelLeft />恢复当前模式默认布局</CommandItem>
        </CommandGroup>}
        <CommandGroup heading="项目文件">{files?.map((file) => <CommandItem key={file.path} value={file.path} onSelect={() => run(() => onOpenFile(file.path))}><FileCode2 /><span className="font-mono text-xs">{file.path}</span></CommandItem>)}</CommandGroup>
      </CommandList>
    </CommandDialog>
  </>
}
