/**
 * Monaco 本地打包配置（不依赖 CDN）。
 *
 * monaco-editor 0.5x 在打包器环境下通过 `new Worker(new URL(...))`
 * 自行创建语言/基础 worker（含 esmModuleLocationBundler 描述符），
 * Vite 会原生处理这些 URL 引用，因此无需手动 `?worker` 导入——
 * 该包的 exports 映射也无法通过深层路径静态导入 worker。
 */
import { loader } from '@monaco-editor/react'
import * as monaco from 'monaco-editor'
import { useAppearanceStore } from '../stores/appearanceStore'
import { THEME_PALETTES, readableAccent } from './appearance'

let configured = false

export function configureMonaco(): typeof monaco {
  if (configured) return monaco
  configured = true
  // 让 @monaco-editor/react 使用本地打包的 monaco 实例而非 CDN。
  const updateTheme = () => {
    const p = useAppearanceStore.getState().preferences
    const c = THEME_PALETTES[p.theme]
    monaco.editor.defineTheme('projectweave', { base: p.theme === 'paper' ? 'vs' : 'vs-dark', inherit: true, rules: [], colors: {
      'editor.background': c.editor, 'editor.foreground': c.ink, 'editorLineNumber.foreground': c.faint,
      'editor.lineHighlightBackground': c.raised, 'editor.selectionBackground': `${p.accent}55`, 'editorWidget.background': c.raised,
      'editorCursor.foreground': readableAccent(p.accent, c.editor), 'editorLineNumber.activeForeground': c.ink,
    } })
    monaco.editor.setTheme('projectweave')
  }
  updateTheme()
  const unsubscribe = useAppearanceStore.subscribe((state, previous) => {
    if (state.preferences.theme !== previous.preferences.theme || state.preferences.accent !== previous.preferences.accent) updateTheme()
  })
  if (import.meta.hot) import.meta.hot.dispose(unsubscribe)
  loader.config({ monaco })
  return monaco
}
