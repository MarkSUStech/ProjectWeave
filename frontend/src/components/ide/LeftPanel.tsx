import { lazy, Suspense, useMemo, useState } from 'react'
import { Badge } from '../ui/Badge'
import type { FileMeta, Project, SnapshotMeta } from '../../types'
import { formatDateTime } from '../../lib/labels'

import { FileCode2, Folder, ChevronRight, ChevronDown, MoreHorizontal, Pencil, Trash2 } from 'lucide-react'
import { Button } from '../ui/Button'
import { PanelTabs } from '../ui/PanelTabs'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '../ui/upstream/dialog'
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem } from '../ui/upstream/dropdown-menu'
const CodeDiff = lazy(() => import('./CodeDiff'))

/** 由扁平路径构建的目录树节点。 */
type TreeItem =
  | { type: 'file'; name: string; path: string }
  | { type: 'folder'; name: string; path: string; children: TreeItem[] }

function buildTree(files: FileMeta[]): TreeItem[] {
  const root: Extract<TreeItem, { type: 'folder' }> = { type: 'folder', name: '', path: '', children: [] }
  for (const file of files) {
    const segments = file.path.split('/')
    let node = root
    for (let i = 0; i < segments.length - 1; i += 1) {
      const segment = segments[i]
      let child = node.children.find(
        (c) => c.type === 'folder' && c.name === segment,
      ) as Extract<TreeItem, { type: 'folder' }> | undefined
      if (!child) {
        child = {
          type: 'folder',
          name: segment,
          path: segments.slice(0, i + 1).join('/'),
          children: [],
        }
        node.children.push(child)
      }
      node = child
    }
    node.children.push({ type: 'file', name: segments[segments.length - 1], path: file.path })
  }
  const sortFolder = (folder: Extract<TreeItem, { type: 'folder' }>): void => {
    folder.children.sort((a, b) => {
      if (a.type !== b.type) return a.type === 'folder' ? -1 : 1
      return a.name.localeCompare(b.name)
    })
    folder.children.forEach((child) => {
      if (child.type === 'folder') sortFolder(child)
    })
  }
  sortFolder(root)
  return root.children
}

export interface HistoryTabApi {
  currentContent?: string
  history: SnapshotMeta[] | null
  error: string | null
  preview: { id: string; content: string } | null
  previewLoading: boolean
  restoring: boolean
  onPreview: (snapshotId: string) => void
  onRestore: (snapshotId: string) => void
}

export interface LeftPanelProps {
  view?: 'files' | 'tasks' | 'history'
  project: Project
  files: FileMeta[] | null
  openPath: string | null
  onOpenFile: (path: string) => void
  onCreateFile: (path: string) => Promise<boolean>
  onRenameFile: (path: string, newPath: string) => Promise<boolean>
  onDeleteFile: (path: string) => Promise<boolean>
  historyApi: HistoryTabApi
}

function FileRow({
  item,
  depth,
  openPath,
  collapsed,
  onToggleFolder,
  onOpenFile,
  onRenameFile,
  onDeleteFile,
}: {
  item: TreeItem
  depth: number
  openPath: string | null
  collapsed: Set<string>
  onToggleFolder: (path: string) => void
  onOpenFile: (path: string) => void
  onRenameFile: (path: string) => void
  onDeleteFile: (path: string) => void
}) {
  const paddingLeft = 8 + depth * 12
  if (item.type === 'folder') {
    const isCollapsed = collapsed.has(item.path)
    return (
      <>
        <button
          type="button"
          onClick={() => onToggleFolder(item.path)}
          className="flex w-full items-center gap-2 rounded-md px-1.5 py-2 text-left text-[13px] text-ink-dim hover:bg-panel-2 hover:text-ink"
          style={{ paddingLeft }}
        >
          {isCollapsed ? <ChevronRight className="size-3" /> : <ChevronDown className="size-3" />}
          <Folder className="size-3.5 text-ink-faint" /><span>{item.name}</span>
        </button>
        {!isCollapsed &&
          item.children.map((child) => (
            <FileRow
              key={child.path}
              item={child}
              depth={depth + 1}
              openPath={openPath}
              collapsed={collapsed}
              onToggleFolder={onToggleFolder}
              onOpenFile={onOpenFile}
              onRenameFile={onRenameFile}
              onDeleteFile={onDeleteFile}
            />
          ))}
      </>
    )
  }
  const active = openPath === item.path
  return (
    <div
      className={`group flex items-center justify-between rounded-md pr-1 ${
        active ? 'bg-panel-2 text-ink' : 'text-ink-dim hover:bg-panel-2'
      }`}
      style={{ paddingLeft }}
    >
      <button
        type="button"
        onClick={() => onOpenFile(item.path)}
        className="flex min-w-0 flex-1 items-center gap-2 truncate py-2 text-left text-[13px]"
        title={item.path}
      >
        <FileCode2 className="size-3.5 shrink-0 text-accent" /><span className="truncate">{item.name}</span>
      </button>
      <DropdownMenu><DropdownMenuTrigger asChild>
        <button type="button" aria-label={`操作 ${item.path}`} className="rounded p-1 text-ink-faint opacity-50 hover:bg-panel-2 hover:text-ink hover:opacity-100 focus-visible:opacity-100"><MoreHorizontal className="size-3.5" /></button>
      </DropdownMenuTrigger><DropdownMenuContent align="end" className="min-w-36">
        <DropdownMenuItem onSelect={() => onRenameFile(item.path)}><Pencil />重命名</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => onDeleteFile(item.path)} className="text-danger"><Trash2 />删除文件</DropdownMenuItem>
      </DropdownMenuContent></DropdownMenu>
    </div>
  )
}

/** 快照历史页签：当前打开文件的历史版本（查看 / 恢复）。 */
function HistoryTab({ openPath, api }: { openPath: string | null; api: HistoryTabApi }) {
  const [restoreTarget, setRestoreTarget] = useState<SnapshotMeta | null>(null)
  const [compareId, setCompareId] = useState<string | null>(null)
  if (openPath === null) {
    return (
      <p className="px-2 py-3 text-xs leading-relaxed text-ink-faint">
        打开一个文件后，这里会显示它的历史版本（每次覆盖保存前的旧内容）。
      </p>
    )
  }
  return (
    <div className="space-y-1.5 p-1.5">
      <p className="truncate font-mono text-[11px] text-ink-dim" title={openPath}>
        {openPath}
      </p>
      {api.error && <p className="text-xs text-danger">{api.error}</p>}
      {api.history === null && <p className="px-1 py-2 text-xs text-ink-faint">加载中…</p>}
      {api.history !== null && api.history.length === 0 && (
        <p className="px-1 py-2 text-xs leading-relaxed text-ink-faint">
          还没有历史版本。修改并保存（含自动保存）后，被覆盖的内容会出现在这里。
        </p>
      )}
      {api.history?.map((snapshot) => (
        <div key={snapshot.id} className="rounded border border-edge-soft bg-panel-2">
          <div className="flex items-center justify-between gap-2 px-2 py-1">
            <button
              type="button"
              onClick={() => api.onPreview(snapshot.id)}
              className="min-w-0 flex-1 text-left text-[11px] text-ink-dim hover:text-ink"
              title="查看内容"
            >
              <span className="block">{formatDateTime(snapshot.createdAt)}</span>
              <span className="font-mono text-[10px] text-ink-faint">
                {snapshot.size}B · {snapshot.sha256}
              </span>
            </button>
            <Button size="sm" variant="ghost" onClick={() => { setCompareId(snapshot.id); if (api.preview?.id !== snapshot.id) api.onPreview(snapshot.id) }}>比较</Button>
            <button
              type="button"
              disabled={api.restoring}
              onClick={() => setRestoreTarget(snapshot)}
              className="shrink-0 rounded border border-edge px-1.5 py-0.5 text-[11px] text-ink-dim hover:border-accent/50 hover:text-ink disabled:opacity-50"
            >
              恢复
            </button>
          </div>
          {api.preview?.id === snapshot.id && (
            <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-all border-t border-edge-soft px-2 py-1.5 font-mono text-[10px] leading-relaxed text-ink-dim">
              {api.preview.content.slice(0, 5000)}
              {api.preview.content.length > 5000 ? '\n…（截断显示）' : ''}
            </pre>
          )}
        </div>
      ))}
      {api.previewLoading && <p className="px-1 text-[11px] text-ink-faint">读取内容…</p>}
      <Dialog open={compareId !== null} onOpenChange={(open) => { if (!open) setCompareId(null) }}>
        <DialogContent className="flex h-[75vh] max-w-[90vw] flex-col sm:max-w-[1100px]">
          <DialogHeader><DialogTitle>历史快照与当前草稿</DialogTitle><DialogDescription>{openPath} · 左侧为历史内容，右侧为当前编辑内容；比较不会保存文件。</DialogDescription></DialogHeader>
          <div className="min-h-0 flex-1">
            {api.preview?.id === compareId ? <Suspense fallback={<p className="text-xs text-ink-dim">正在加载差异组件…</p>}><CodeDiff original={api.preview.content} modified={api.currentContent ?? ''} path={openPath} /></Suspense> : <p role="status" className="text-xs text-ink-dim">{api.error ?? '正在读取快照…'}</p>}
          </div>
        </DialogContent>
      </Dialog>
      <Dialog open={restoreTarget !== null} onOpenChange={(open) => { if (!open) setRestoreTarget(null) }}>
        <DialogContent><DialogHeader><DialogTitle>恢复历史版本</DialogTitle><DialogDescription>恢复到 {restoreTarget && formatDateTime(restoreTarget.createdAt)} 的版本，当前内容会先进入历史。</DialogDescription></DialogHeader>
          <DialogFooter><Button variant="outline" onClick={() => setRestoreTarget(null)}>取消</Button><Button disabled={api.restoring} onClick={() => { if (restoreTarget) api.onRestore(restoreTarget.id); setRestoreTarget(null) }}>确认恢复</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

/** 左侧面板：文件 / 任务 / 历史三个页签。 */
export function LeftPanel(props: LeftPanelProps) {
  const { project, files, openPath, onOpenFile, onCreateFile, onRenameFile, onDeleteFile, historyApi } = props
  const [selectedTab, setTab] = useState<'files' | 'tasks' | 'history'>('files')
  const tab = props.view ?? selectedTab
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [creating, setCreating] = useState(false)
  const [newPath, setNewPath] = useState('')
  const [operation, setOperation] = useState<{ type: 'rename' | 'delete'; path: string } | null>(null)
  const [operationPath, setOperationPath] = useState('')
  const [busy, setBusy] = useState(false)
  const [operationError, setOperationError] = useState<string | null>(null)

  const tree = useMemo(() => buildTree(files ?? []), [files])

  const toggleFolder = (path: string) =>
    setCollapsed((current) => {
      const next = new Set(current)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })

  const submitCreate = async (event: React.FormEvent) => {
    event.preventDefault()
    const path = newPath.trim()
    if (!path) return
    const ok = await onCreateFile(path)
    if (ok) {
      setNewPath('')
      setCreating(false)
    }
  }

  const handleRename = (path: string) => { setOperation({ type: 'rename', path }); setOperationPath(path); setOperationError(null) }
  const handleDelete = (path: string) => { setOperation({ type: 'delete', path }); setOperationError(null) }
  const submitOperation = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!operation || busy) return
    setBusy(true)
    setOperationError(null)
    try {
      const ok = operation.type === 'rename' ? await onRenameFile(operation.path, operationPath.trim()) : await onDeleteFile(operation.path)
      if (ok) setOperation(null)
      else setOperationError('操作未完成，请检查文件路径或稍后重试。')
    } catch { setOperationError('文件操作失败，请重试。') }
    finally { setBusy(false) }
  }

  const content = (
    <>

      {tab === 'files' && (
        <>
          <div className="flex items-center justify-between border-b border-edge-soft px-2 py-1.5">
            <span className="text-[11px] text-ink-faint">
              {files === null ? '加载中…' : `${files.length} 个文件`}
            </span>
            <button
              type="button"
              onClick={() => setCreating((v) => !v)}
              title="新建文件"
              className="rounded px-1.5 py-0.5 text-xs text-ink-dim hover:bg-panel-2 hover:text-ink"
            >
              + 文件
            </button>
          </div>
          {creating && (
            <form onSubmit={submitCreate} className="border-b border-edge-soft p-2">
              <input
                autoFocus
                value={newPath}
                onChange={(e) => setNewPath(e.target.value)}
                placeholder="src/new-file.ts"
                className="w-full rounded border border-edge bg-panel-2 px-2 py-1 font-mono text-xs text-ink placeholder:text-ink-faint focus:border-accent/60 focus:outline-none"
                spellCheck={false}
              />
              <div className="mt-1.5 flex justify-end gap-1.5">
                <button
                  type="button"
                  onClick={() => {
                    setCreating(false)
                    setNewPath('')
                  }}
                  className="rounded px-2 py-0.5 text-[11px] text-ink-faint hover:text-ink"
                >
                  取消
                </button>
                <button
                  type="submit"
                  disabled={!newPath.trim()}
                  className="rounded bg-primary px-2 py-0.5 text-[11px] font-medium text-primary-foreground disabled:opacity-50"
                >
                  创建
                </button>
              </div>
            </form>
          )}
          <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
            {files === null && <p className="px-2 py-3 text-xs text-ink-faint">正在加载文件树…</p>}
            {files !== null && files.length === 0 && (
              <p className="px-2 py-3 text-xs leading-relaxed text-ink-faint">
                项目还没有文件。点击上方「+ 文件」创建第一个文件。
              </p>
            )}
            {tree.map((item) => (
              <FileRow
                key={item.path}
                item={item}
                depth={0}
                openPath={openPath}
                collapsed={collapsed}
                onToggleFolder={toggleFolder}
                onOpenFile={onOpenFile}
                onRenameFile={handleRename}
                onDeleteFile={handleDelete}
              />
            ))}
          </div>
        </>
      )}

      {tab === 'tasks' && (
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {project.milestones.length === 0 ? (
            <div className="flex flex-col items-center gap-1.5 rounded-md border border-dashed border-edge p-4 text-center">
              <div className="text-sm font-medium text-ink-dim">任务图未生成</div>
              <p className="text-xs leading-relaxed text-ink-faint">
                课程引擎将基于项目规格与能力诊断生成任务（P2）。当前可以先在文件页签中编写代码。
              </p>
              <Badge>P2</Badge>
            </div>
          ) : (
            <ul className="space-y-1">
              {project.milestones.map((milestone) => (
                <li key={milestone.id}>
                  <button
                    type="button"
                    className="w-full rounded px-2 py-1.5 text-left text-xs text-ink-dim hover:bg-panel-2 hover:text-ink"
                  >
                    <span className="block">{milestone.title}</span>
                    <span className="mt-1 block text-[10px] text-ink-faint">
                      {formatDateTime(project.createdAt)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {tab === 'history' && (
        <div className="min-h-0 flex-1 overflow-y-auto">
          <HistoryTab openPath={openPath} api={historyApi} />
        </div>
      )}
    </>
  )
  return (
    <aside className="flex h-full min-h-0 flex-col bg-panel">
      {props.view ? content : <PanelTabs value={tab} onChange={setTab} items={[{ id: 'files', label: '文件' }, { id: 'tasks', label: '任务' }, { id: 'history', label: '历史' }]} label="项目资源">{content}</PanelTabs>}
      <Dialog open={operation !== null} onOpenChange={(open) => { if (!open && !busy) setOperation(null) }}>
        <DialogContent><form onSubmit={(event) => void submitOperation(event)} className="space-y-4">
          <DialogHeader><DialogTitle>{operation?.type === 'delete' ? '删除文件' : '重命名文件'}</DialogTitle><DialogDescription>{operation?.type === 'delete' ? `确定删除「${operation.path}」？文件与历史快照将删除，此操作不可恢复。` : '输入新的相对路径，历史快照会随文件迁移。'}</DialogDescription></DialogHeader>
          {operation?.type === 'rename' && <div><label htmlFor="rename-path" className="mb-2 block text-xs text-ink-dim">新文件路径</label><input id="rename-path" value={operationPath} onChange={(event) => setOperationPath(event.target.value)} className="w-full rounded-md border border-edge bg-panel-2 px-3 py-2 font-mono text-sm" required disabled={busy} /></div>}
          {operationError && <p role="alert" className="text-xs text-danger">{operationError}</p>}
          <DialogFooter><Button type="button" variant="outline" disabled={busy} onClick={() => setOperation(null)}>取消</Button><Button type="submit" variant={operation?.type === 'delete' ? 'danger' : 'primary'} disabled={busy || (operation?.type === 'rename' && (!operationPath.trim() || operationPath.trim() === operation.path))}>{busy ? '处理中…' : operation?.type === 'delete' ? '确认删除' : '保存路径'}</Button></DialogFooter>
        </form></DialogContent>
      </Dialog>
    </aside>
  )
}
