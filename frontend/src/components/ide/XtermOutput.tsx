import { useEffect, useRef, useState } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { terminalLine } from '../../lib/terminal'
import { useRunStore } from '../../stores/runStore'
import { useAppearanceStore } from '../../stores/appearanceStore'
import { EDITOR_FONTS, THEME_PALETTES } from '../../lib/appearance'

function terminalTheme(theme: keyof typeof THEME_PALETTES) {
  const c = THEME_PALETTES[theme]
  return { background: c.editor, foreground: c.ink, black: c.editor, brightBlack: c.faint, white: c.ink, brightWhite: c.ink, red: c.danger, brightRed: c.danger,
    yellow: c.warn, brightYellow: c.warn, cyan: theme === 'paper' ? '#137e91' : '#79c5d6', brightCyan: theme === 'paper' ? '#137e91' : '#79c5d6', green: c.ok, brightGreen: c.ok }
}

/** xterm 只读输出适配器；执行仍由真实 Worker 管线负责。 */
export default function XtermOutput() {
  const container = useRef<HTMLDivElement>(null)
  const terminal = useRef<Terminal | null>(null)
  const fitRef = useRef<FitAddon | null>(null)
  const p = useAppearanceStore((s) => s.preferences)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    if (!container.current) return
    const initial = useAppearanceStore.getState().preferences
    const term = new Terminal({ disableStdin: true, screenReaderMode: true, convertEol: true,
      fontSize: initial.terminalFontSize, fontFamily: EDITOR_FONTS[initial.editorFont], scrollback: 2500,
      theme: terminalTheme(initial.theme) })
    terminal.current = term
    const fit = new FitAddon()
    fitRef.current = fit
    let observer: ResizeObserver | undefined
    let unsubscribe: (() => void) | undefined
    try {
      term.loadAddon(fit)
      term.open(container.current)
      const resize = () => { if (container.current && container.current.clientWidth > 0 && container.current.clientHeight > 0) fit.fit() }
      observer = new ResizeObserver(resize)
      observer.observe(container.current)
      resize()
      let previous: number[] = []
      const render = () => {
        const entries = useRunStore.getState().entries
        const ids = entries.map((entry) => entry.id)
        const appendOnly = previous.length > 0 && previous.every((id, index) => id === ids[index])
        if (!appendOnly) term.reset()
        if (ids.length === 0) term.write('\x1b[90m尚无输出。打开 .js / .ts 文件后点击「运行」（Ctrl+Enter）。\x1b[0m\r\n')
        else for (const entry of entries.slice(appendOnly ? previous.length : 0)) term.write(terminalLine(entry))
        previous = ids
      }
      render()
      unsubscribe = useRunStore.subscribe((state, prev) => { if (state.entries !== prev.entries) render() })
    } catch {
      setError('终端初始化失败，请重新打开终端页签。')
    }
    return () => { observer?.disconnect(); unsubscribe?.(); terminal.current = null; fitRef.current = null; term.dispose() }
  }, [])
  useEffect(() => {
    const term = terminal.current
    if (!term) return
    term.options.theme = terminalTheme(p.theme)
    term.options.fontSize = p.terminalFontSize
    term.options.fontFamily = EDITOR_FONTS[p.editorFont]
    if (container.current && container.current.clientWidth > 0 && container.current.clientHeight > 0) {
      try { fitRef.current?.fit() } catch { setError('终端显示调整失败，请重新打开终端页签。') }
    }
  }, [p.theme, p.terminalFontSize, p.editorFont])
  return <div className="relative h-full min-h-0" aria-label="运行输出终端">
    <div ref={container} className="h-full min-h-0 px-3 py-2" />
    {error && <p role="alert" className="absolute inset-0 bg-panel p-3 text-xs text-danger">{error}</p>}
  </div>
}
