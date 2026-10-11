import Editor from '@monaco-editor/react'
import { useEffect, useRef } from 'react'
import type { editor as MonacoEditor } from 'monaco-editor'
import { configureMonaco } from '../../lib/monaco'
import { isAnyTestPath, canRunPath } from '../../lib/runner/runRemote'
import { Button } from '../ui/Button'
import { PlaceholderState } from '../ui/PlaceholderState'
import { FileCode2, BugPlay, Play, StepForward, CornerDownRight, LogOut, Square } from 'lucide-react'
import { useAppearanceStore } from '../../stores/appearanceStore'
import { useDebugStore } from '../../stores/debugStore'
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
    cpp: 'cpp',
    cc: 'cpp',
    cxx: 'cpp',
    h: 'cpp',
    hpp: 'cpp',
    hh: 'cpp',
    hxx: 'cpp',
    c: 'c',
    txt: 'plaintext',
    yml: 'yaml',
    yaml: 'yaml',
  }
  return map[extension] ?? 'plaintext'
}

/** C++ 文件判定（断点交互仅对远程调试语言开放，v1 = C++）。 */
function detectLanguageOf(path: string): string {
  return ['cpp', 'cc', 'cxx', 'h', 'hpp', 'hh', 'hxx'].includes(path.split('.').pop()?.toLowerCase() ?? '')
    ? 'cpp'
    : 'other'
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
  /** 开始调试（由 IdePage 提供 VFS 组装；C++ 文件可用）。 */
  onDebugStart?: () => void
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
  onDebugStart,
}: EditorPanelProps) {
  const p = useAppearanceStore((s) => s.preferences)
  const editorRef = useRef<MonacoEditor.IStandaloneCodeEditor | null>(null)
  const decorationsRef = useRef<MonacoEditor.IEditorDecorationsCollection | null>(null)
  const breakpoints = useDebugStore((s) => s.breakpoints)
  const snapshot = useDebugStore((s) => s.snapshot)
  const toggleBreakpoint = useDebugStore((s) => s.toggleBreakpoint)
  const debugCommand = useDebugStore((s) => s.command)
  const debugStop = useDebugStore((s) => s.stop)

  // onMount 一次性回调读取最新状态用的 ref（避免闭包过期：切换文件后断点加错文件）
  const openPathRef = useRef(openPath)
  openPathRef.current = openPath
  const toggleBreakpointRef = useRef(toggleBreakpoint)
  toggleBreakpointRef.current = toggleBreakpoint

  useEffect(() => {
    configureMonaco()
  }, [])

  // 断点与暂停行装饰：增删断点/暂停位置变化时刷新（不重建编辑器实例）
  useEffect(() => {
    const editor = editorRef.current
    if (!editor || openPath === null) return
    const model = editor.getModel()
    if (!model) return
    const decorations: MonacoEditor.IModelDeltaDecoration[] = []
    for (const line of breakpoints[openPath] ?? []) {
      decorations.push({
        range: { startLineNumber: line, startColumn: 1, endLineNumber: line, endColumn: 1 },
        options: {
          isWholeLine: false,
          glyphMarginClassName: 'pw-breakpoint-glyph',
          overviewRuler: { color: '#e5534b', position: 4 },
          stickiness: 1,
        },
      })
    }
    const location = snapshot?.location
    if (snapshot?.status === 'paused' && location?.file === openPath && location.line !== null) {
      decorations.push({
        range: { startLineNumber: location.line, startColumn: 1, endLineNumber: location.line, endColumn: 1 },
        options: {
          isWholeLine: true,
          className: 'pw-paused-line',
          linesDecorationsClassName: 'pw-paused-line-marker',
          overviewRuler: { color: '#d29922', position: 4 },
        },
      })
    }
    if (decorationsRef.current) {
      decorationsRef.current.set(decorations)
    } else {
      decorationsRef.current = editor.createDecorationsCollection(decorations)
    }
  }, [openPath, content, breakpoints, snapshot?.status, snapshot?.location])

  const handleEditorMount = (editor: MonacoEditor.IStandaloneCodeEditor, monaco: typeof import('monaco-editor')) => {
    editorRef.current = editor
    decorationsRef.current = null
    // onMount 只执行一次：通过 ref 读取当前文件（闭包里的 openPath 切换文件后会过期）
    editor.onMouseDown((e) => {
      const currentPath = openPathRef.current
      if (currentPath === null) return
      if (detectLanguageOf(currentPath) !== 'cpp') return
      const targetType = e.target.type
      if (
        targetType === monaco.editor.MouseTargetType.GUTTER_GLYPH_MARGIN ||
        targetType === monaco.editor.MouseTargetType.GUTTER_LINE_NUMBERS
      ) {
        const line = e.target.position?.lineNumber
        if (line !== undefined) toggleBreakpointRef.current(currentPath, line)
      }
    })
    // 可发现性（VS Code 惯例）：C++ 文件悬停行号区域时显示半透明圆点，提示可点击设断点
    let hoverDecoration: MonacoEditor.IEditorDecorationsCollection | null = null
    editor.onMouseMove((e) => {
      const currentPath = openPathRef.current
      const inGutter =
        e.target.type === monaco.editor.MouseTargetType.GUTTER_GLYPH_MARGIN ||
        e.target.type === monaco.editor.MouseTargetType.GUTTER_LINE_NUMBERS
      const line = e.target.position?.lineNumber
      hoverDecoration?.clear()
      hoverDecoration = null
      if (!inGutter || currentPath === null || detectLanguageOf(currentPath) !== 'cpp' || line === undefined) return
      const alreadySet = (useDebugStore.getState().breakpoints[currentPath] ?? []).includes(line)
      if (alreadySet) return  // 已有断点的行不再显示幽灵圆点
      hoverDecoration = editor.createDecorationsCollection([{
        range: { startLineNumber: line, startColumn: 1, endLineNumber: line, endColumn: 1 },
        options: { isWholeLine: false, glyphMarginClassName: 'pw-breakpoint-hover-glyph', stickiness: 1 },
      }])
    })
    editor.onMouseLeave(() => {
      hoverDecoration?.clear()
      hoverDecoration = null
    })
  }

  const canRun = openPath !== null && canRunPath(openPath) && !running
  const isTest = openPath !== null && isAnyTestPath(openPath)

  // 调试工具栏可用性
  const isCpp = openPath !== null && detectLanguageOf(openPath) === 'cpp'
  const debugActive = snapshot !== null && snapshot.status !== 'terminated'
  const paused = snapshot?.status === 'paused'
  const busy = snapshot !== null && ['creating', 'building', 'configuring'].includes(snapshot.status)

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
                : isAnyTestPath(openPath)
                  ? '运行项目全部测试（TS 浏览器沙箱 / Python 远程沙箱，Ctrl+Enter）'
                  : canRunPath(openPath)
                    ? '运行当前编辑内容（TS 浏览器沙箱 / Python 远程沙箱，Ctrl+Enter）'
                    : '当前文件类型不可执行'
            }
          >
            {running ? '运行中…' : isTest ? '▶ 测试' : '▶ 运行'}
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
          {/* 调试工具栏（P4.5a）：C++ 专用；真实 LLDB 沙箱会话 */}
          <span className="mx-1 inline-flex items-center gap-0.5 border-l border-edge-soft pl-1.5">
            <Button
              size="sm"
              variant="outline"
              disabled={!isCpp || !onDebugStart || debugActive || busy}
              onClick={() => onDebugStart?.()}
              title={isCpp ? '启动 LLDB 调试会话（在断点处暂停）' : '调试当前仅支持 C++ 文件'}
            >
              <BugPlay className="size-3.5" />
              调试
            </Button>
            {debugActive && (
              <>
                <Button size="sm" variant="outline" disabled={!paused} onClick={() => void debugCommand('continue')} title="继续执行（到下一断点/结束）">
                  <Play className="size-3.5" />
                </Button>
                <Button size="sm" variant="outline" disabled={!paused} onClick={() => void debugCommand('next')} title="单步跳过（next）">
                  <StepForward className="size-3.5" />
                </Button>
                <Button size="sm" variant="outline" disabled={!paused} onClick={() => void debugCommand('stepIn')} title="单步进入（stepIn）">
                  <CornerDownRight className="size-3.5" />
                </Button>
                <Button size="sm" variant="outline" disabled={!paused} onClick={() => void debugCommand('stepOut')} title="单步跳出（stepOut）">
                  <LogOut className="size-3.5" />
                </Button>
                <Button size="sm" variant="outline" onClick={() => void debugStop()} title="停止调试并回收沙箱">
                  <Square className="size-3.5 text-danger" />
                </Button>
              </>
            )}
          </span>
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
            onMount={handleEditorMount}
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
              glyphMargin: true,
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
