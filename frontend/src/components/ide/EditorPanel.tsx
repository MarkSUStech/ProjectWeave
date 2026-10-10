import Editor from '@monaco-editor/react'
import { useEffect } from 'react'
import { configureMonaco } from '../../lib/monaco'
import { isRunnablePath, isTestPath } from '../../lib/runner/runFile'
import { Button } from '../ui/Button'
import { PlaceholderState } from '../ui/PlaceholderState'
import { FileCode2 } from 'lucide-react'
import { useAppearanceStore } from '../../stores/appearanceStore'
import { EDITOR_FONTS } from '../../lib/appearance'

/** 根据扩展名推断 Monaco 语言。 */
function languageOf(path: string): string {
  const extension = path.split('.').pop()?.toLowerCase() ?? ''
  const map: Record<string, string> = {
    ts: 'typescript',
    tsx: 'typescript',
    js: 'javascript',
    jsx: 'javascript',
    json: 'json',
    md: 'markdown',
    css: 'css',
    html: 'html',
    py: 'python',
    yml: 'yaml',
    yaml: 'yaml',
  }
  return map[extension] ?? 'plaintext'
}

export interface EditorPanelProps {
  openPath: string | null
  content: string
  dirty: boolean
  saving: boolean
  error: string | null
  lastSavedAt: string | null
  /** 是否正在浏览器运行器中执行。 */
  running: boolean
  onChange: (content: string) => void
  onSave: () => void
  onRun: () => void
}

/** 中央编辑器：Monaco + 服务器端文件（保存 = PUT 持久化，运行 = 浏览器 Worker 沙箱）。 */
export function EditorPanel({
  openPath,
  content,
  dirty,
  saving,
  error,
  lastSavedAt,
  running,
  onChange,
  onSave,
  onRun,
}: EditorPanelProps) {
  const p = useAppearanceStore((s) => s.preferences)
  useEffect(() => {
    configureMonaco()
  }, [])

  const canRun = openPath !== null && isRunnablePath(openPath) && !running
  const isTestFile = openPath !== null && isTestPath(openPath)

  // Ctrl/Cmd + S 保存；Ctrl/Cmd + Enter 运行/运行测试（覆盖浏览器默认行为）
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey)) return
      const key = event.key.toLowerCase()
      // 设置弹窗内的组合键不应触发背后文件的保存/执行。
      if (useAppearanceStore.getState().open && (key === 's' || key === 'enter')) { event.preventDefault(); return }
      if (key === 's') {
        event.preventDefault()
        onSave()
      } else if (key === 'enter') {
        event.preventDefault()
        if (canRun) onRun()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onSave, onRun, canRun])

  return (
    <div className="workspace-editor flex h-full min-h-0 min-w-0 flex-col">
      <div className="editor-toolbar flex shrink-0 items-center justify-between gap-2 border-b border-edge-soft bg-panel px-4">
        <span className="inline-flex min-w-0 items-center gap-2 truncate text-xs text-ink-dim">
          <FileCode2 className="size-3.5 shrink-0 text-accent" />
          {openPath ?? '未打开文件'}
        </span>
        <div className="flex shrink-0 items-center gap-2">
          <span
            className={`text-[11px] ${dirty ? 'text-warn' : 'text-ink-faint'}`}
            role="status"
          >
            {saving ? '保存中…' : dirty ? '● 未保存 · 将自动保存' : lastSavedAt ? `已保存 ${lastSavedAt}` : ''}
          </span>
          <Button
            size="sm"
            variant="outline"
            disabled={!canRun}
            onClick={onRun}
            title={
              openPath === null
                ? '未打开文件'
                : isTestPath(openPath)
                  ? '在浏览器 Worker 沙箱中运行项目全部测试（Ctrl+Enter）'
                  : isRunnablePath(openPath)
                    ? '在浏览器 Worker 沙箱中运行当前编辑内容（Ctrl+Enter）'
                    : '浏览器运行器仅支持 .js / .ts 文件'
            }
          >
            {running ? '运行中…' : isTestFile ? '▶ 测试' : '▶ 运行'}
          </Button>
          <Button
            size="sm"
            variant={dirty ? 'primary' : 'outline'}
            disabled={!openPath || !dirty || saving}
            onClick={onSave}
            title="保存到服务器（Ctrl+S）"
          >
            保存
          </Button>
        </div>
      </div>

      {error && (
        <p role="alert" className="border-b border-danger/30 bg-danger/10 px-3 py-1.5 text-xs text-danger">
          {error}
        </p>
      )}

      <div className="min-h-0 flex-1">
        {openPath === null ? (
          <PlaceholderState
            title="未打开文件"
            description="在左侧文件树中选择一个文件开始编辑；保存会写入服务器数据库，运行在浏览器沙箱中执行。"
          />
        ) : (
          <Editor
            height="100%"
            theme="projectweave"
            language={languageOf(openPath)}
            value={content}
            onChange={(value) => onChange(value ?? '')}
            options={{
              fontSize: p.editorFontSize,
              lineHeight: Math.round(p.editorFontSize * p.editorLineHeight),
              fontFamily: EDITOR_FONTS[p.editorFont],
              fontLigatures: p.ligatures,
              wordWrap: p.wordWrap ? 'on' : 'off',
              lineNumbers: p.lineNumbers ? 'on' : 'off',
              minimap: { enabled: p.minimap },
              scrollBeyondLastLine: false,
              automaticLayout: true,
              padding: { top: 18, bottom: 12 },
            }}
            loading={
              <div className="flex h-full items-center justify-center text-xs text-ink-faint">
                正在加载编辑器…
              </div>
            }
          />
        )}
      </div>
    </div>
  )
}
