import { useEffect, useLayoutEffect, useRef } from 'react'
import { DiffEditor, type MonacoDiffEditor } from '@monaco-editor/react'
import { configureMonaco } from '../../lib/monaco'
import { releaseDiffModels } from '../../lib/diffLifecycle'
import { useAppearanceStore } from '../../stores/appearanceStore'
import { EDITOR_FONTS } from '../../lib/appearance'

/** 只读差异查看，不执行或保存任何补丁。 */
export default function CodeDiff({ original, modified, path }: { original: string; modified: string; path: string }) {
  const p = useAppearanceStore((s) => s.preferences)
  const editorRef = useRef<MonacoDiffEditor | null>(null)
  useEffect(() => { configureMonaco() }, [])
  // 父组件 layout cleanup 先解除绑定；子组件随后释放 widget，不留下持久模型。
  useLayoutEffect(() => () => {
    if (editorRef.current) releaseDiffModels(editorRef.current)
    editorRef.current = null
  }, [])
  const extension = path.split('.').pop()
  const language = extension === 'ts' ? 'typescript' : extension === 'js' ? 'javascript' : extension === 'md' ? 'markdown' : 'plaintext'
  return <DiffEditor height="100%" theme="projectweave" language={language} original={original} modified={modified}
    keepCurrentOriginalModel keepCurrentModifiedModel onMount={(editor) => { editorRef.current = editor }}
    options={{ readOnly: true, originalEditable: false, automaticLayout: true, minimap: { enabled: false }, fontSize: p.editorFontSize, fontFamily: EDITOR_FONTS[p.editorFont], lineHeight: Math.round(p.editorFontSize * p.editorLineHeight), fontLigatures: p.ligatures, wordWrap: p.wordWrap ? 'on' : 'off', lineNumbers: p.lineNumbers ? 'on' : 'off', renderSideBySide: true, scrollBeyondLastLine: false }}
    loading={<p className="p-4 text-xs text-ink-dim">正在加载代码差异…</p>} />
}
