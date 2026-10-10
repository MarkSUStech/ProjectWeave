import type { Appearance } from '../stores/appearanceStore'

export const THEME_PALETTES = {
  graphite: { app: '#151517', panel: '#1b1b1f', raised: '#242429', editor: '#171719', chrome: '#1e1e22', sidebar: '#19191c', edge: '#36363d', soft: '#2b2b31', ink: '#eeeef2', dim: '#bdbdc8', faint: '#9797a6', ok: '#83d5a6', warn: '#e8bf6a', danger: '#f08080' },
  midnight: { app: '#10151e', panel: '#161d29', raised: '#202c3d', editor: '#111823', chrome: '#192231', sidebar: '#131b27', edge: '#3c4a60', soft: '#28364a', ink: '#edf3fc', dim: '#b9c7dc', faint: '#92a5c0', ok: '#7ed7b3', warn: '#efc279', danger: '#fb8f9b' },
  paper: { app: '#f3f3f5', panel: '#ffffff', raised: '#eaeaef', editor: '#fafafd', chrome: '#f7f7fa', sidebar: '#eaeaef', edge: '#c2c2cc', soft: '#ddddE5', ink: '#25252e', dim: '#51515f', faint: '#6b6b7c', ok: '#247246', warn: '#906100', danger: '#bd303e' },
} as const
export const EDITOR_FONTS = {
  cascadia: '"Cascadia Code", Consolas, monospace',
  jetbrains: '"JetBrains Mono", "Cascadia Code", Consolas, monospace',
  system: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
}

/** 根据强调色亮度选择按钮文字，允许任意安全的十六进制颜色。 */
function luminance(hex: string) {
  const channels = [1, 3, 5].map((start) => {
    const n = parseInt(hex.slice(start, start + 2), 16) / 255
    return n <= 0.04045 ? n / 12.92 : ((n + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
}
export function contrastRatio(a: string, b: string) {
  const x = luminance(a), y = luminance(b)
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)
}
export function accentForeground(hex: string) {
  return contrastRatio(hex, '#151517') > contrastRatio(hex, '#ffffff') ? '#151517' : '#ffffff'
}
/** 强调色用于文字时保持可读，按钮填色仍使用用户原色。 */
export function readableAccent(hex: string, background: string) {
  if (contrastRatio(hex, background) >= 4.5) return hex
  const endpoint = contrastRatio('#000000', background) > contrastRatio('#ffffff', background) ? 0 : 255
  const rgb = [1, 3, 5].map((start) => parseInt(hex.slice(start, start + 2), 16))
  for (let mix = 0.05; mix <= 1.001; mix += 0.05) {
    const adjusted = `#${rgb.map((n) => Math.round(n + (endpoint - n) * mix).toString(16).padStart(2, '0')).join('')}`
    if (contrastRatio(adjusted, background) >= 4.5) return adjusted
  }
  return endpoint === 0 ? '#000000' : '#ffffff'
}
export function appearanceVariables(p: Appearance): Record<string, string> {
  const colors = THEME_PALETTES[p.theme]
  const density = { compact: [30, 40, 28], comfortable: [38, 48, 32], spacious: [44, 56, 38] }[p.density]
  return {
    '--color-app': colors.app, '--color-panel': colors.panel, '--color-panel-2': colors.raised,
    '--color-editor': colors.editor, '--color-edge': colors.edge, '--color-edge-soft': colors.soft,
    '--color-ink': colors.ink, '--color-ink-dim': colors.dim, '--color-ink-faint': colors.faint,
    '--color-accent': readableAccent(p.accent, colors.panel), '--color-accent-strong': readableAccent(p.accent, colors.panel),
    '--color-accent-soft': `color-mix(in srgb, ${p.accent} 16%, ${colors.panel})`,
    '--color-ok': colors.ok, '--color-warn': colors.warn, '--color-danger': colors.danger,
    '--color-background': colors.panel, '--color-foreground': colors.ink,
    '--color-card': colors.panel, '--color-card-foreground': colors.ink,
    '--color-primary': p.accent, '--color-primary-foreground': accentForeground(p.accent),
    '--color-secondary': colors.raised, '--color-secondary-foreground': colors.ink,
    '--color-muted': colors.raised, '--color-muted-foreground': colors.dim,
    '--color-popover': colors.raised, '--color-popover-foreground': colors.ink,
    '--color-accent-foreground': accentForeground(p.accent), '--color-ring': p.accent,
    '--color-border': colors.edge, '--color-input': colors.edge,
    '--pw-chrome': colors.chrome, '--pw-sidebar': colors.sidebar,
    '--pw-card-shadow': p.shadows ? '0 10px 30px -20px #0005, inset 0 1px 0 #ffffff04' : 'none',
    '--radius-sm': `${Math.max(0, p.radius - 4)}px`, '--radius-md': `${Math.max(0, p.radius - 2)}px`,
    '--radius-lg': `${p.radius}px`, '--radius-xl': `${p.radius + (p.radius ? 4 : 0)}px`,
    '--pw-tab-height': `${density[0]}px`, '--pw-toolbar-height': `${density[1]}px`, '--pw-button-height': `${density[2]}px`,
    '--font-mono': EDITOR_FONTS[p.editorFont],
  }
}
export function applyAppearance(p: Appearance, root = document.documentElement) {
  for (const [name, value] of Object.entries(appearanceVariables(p))) root.style.setProperty(name, value)
  root.style.fontSize = `${16 * p.uiScale / 100}px`
  root.style.colorScheme = p.theme === 'paper' ? 'light' : 'dark'
  root.dataset.uiTheme = p.theme
  root.dataset.uiDensity = p.density
  root.dataset.uiTexture = p.texture
  root.dataset.uiMotion = p.motion ? 'system' : 'off'
}
