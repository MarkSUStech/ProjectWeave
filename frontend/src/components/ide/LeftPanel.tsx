import { useMemo, useState } from 'react'
import { Badge } from '../ui/Badge'
import type { FileMeta, Project, SnapshotMeta } from '../../types'
import { formatDateTime } from '../../lib/labels'

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
  history: SnapshotMeta[] | null
  error: string | null
  preview: { id: string; content: string } | null
  previewLoading: boolean
  restoring: boolean
  onPreview: (snapshotId: string) => void
  onRestore: (snapshotId: string) => void
}

export interface LeftPanelProps {
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
          className="flex w-full items-center gap-1 rounded px-1.5 py-1 text-left text-xs text-ink-dim hover:bg-panel-2 hover:text-ink"
          style={{ paddingLeft }}
        >
          <span className="w-3 text-[10px] text-ink-faint">{isCollapsed ? '▸' : '▾'}</span>
          <span>📁 {item.name}</span>
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
      className={`group flex items-center justify-between rounded pr-1 ${
        active ? 'bg-accent-soft text-ink' : 'hover:bg-panel-2'
      }`}
      style={{ paddingLeft }}
    >
      <button
        type="button"
        onClick={() => onOpenFile(item.path)}
        className="min-w-0 flex-1 truncate py-1 text-left text-xs"
        title={item.path}
      >
        <span className={active ? 'text-accent' : ''}>📄 {item.name}</span>
      </button>
      <span className="hidden shrink-0 items-center gap-0.5 group-hover:flex">
        <button
          type="button"
          title="重命名"
          onClick={() => onRenameFile(item.path)}
          className="rounded px-1 text-[11px] text-ink-faint hover:text-ink"
        >
          ✎
        </button>
        <button
          type="button"
          title="删除"
          onClick={() => onDeleteFile(item.path)}
          className="rounded px-1 text-[11px] text-ink-faint hover:text-danger"
        >
          ✕
        </button>
      </span>
    </div>
  )
}

/** 快照历史页签：当前打开文件的历史版本（查看 / 恢复）。 */
function HistoryTab({ openPath, api }: { openPath: string | null; api: HistoryTabApi }) {
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
            <button
              type="button"
              disabled={api.restoring}
              onClick={() => {
                if (window.confirm(`恢复到 ${formatDateTime(snapshot.createdAt)} 的版本？当前内容会先进入历史。`)) {
                  api.onRestore(snapshot.id)
                }
              }}
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
    </div>
  )
}

/** 左侧面板：文件 / 任务 / 历史三个页签。 */
export function LeftPanel(props: LeftPanelProps) {
  const { project, files, openPath, onOpenFile, onCreateFile, onRenameFile, onDeleteFile, historyApi } = props
  const [tab, setTab] = useState<'files' | 'tasks' | 'history'>('files')
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [creating, setCreating] = useState(false)
  const [newPath, setNewPath] = useState('')

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

  const handleRename = (path: string) => {
    const next = window.prompt('新的文件路径：', path)
    if (!next || next.trim() === path) return
    void onRenameFile(path, next.trim())
  }

  const handleDelete = (path: string) => {
    if (!window.confirm(`确定删除「${path}」？此操作不可恢复。`)) return
    void onDeleteFile(path)
  }

  return (
    <aside className="flex min-h-0 flex-col border-r border-edge bg-panel">
      <div className="flex border-b border-edge-soft">
        {(
          [
            ['files', '文件'],
            ['tasks', '任务'],
            ['history', '历史'],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            type="button"
            onClick={() => setTab(value)}
            className={`flex-1 border-b-2 px-3 py-2 text-xs font-medium transition-colors ${
              tab === value
                ? 'border-accent text-ink'
                : 'border-transparent text-ink-faint hover:text-ink-dim'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

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
                  className="rounded bg-accent px-2 py-0.5 text-[11px] font-medium text-white disabled:opacity-50"
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
    </aside>
  )
}
