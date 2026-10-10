import { create } from 'zustand'
import { z } from 'zod'

export const appearanceSchema = z.object({
  theme: z.enum(['graphite', 'midnight', 'paper']).default('graphite'),
  accent: z.string().regex(/^#[0-9a-fA-F]{6}$/).default('#c1b5ff'),
  uiScale: z.number().int().min(90).max(120).default(100),
  density: z.enum(['compact', 'comfortable', 'spacious']).default('comfortable'),
  radius: z.number().int().min(0).max(16).default(8),
  texture: z.enum(['none', 'dots', 'grid']).default('none'),
  shadows: z.boolean().default(true),
  motion: z.boolean().default(true),
  editorFont: z.enum(['cascadia', 'jetbrains', 'system']).default('cascadia'),
  editorFontSize: z.number().int().min(11).max(22).default(14),
  editorLineHeight: z.number().min(1.3).max(2).default(1.65),
  wordWrap: z.boolean().default(false),
  minimap: z.boolean().default(false),
  lineNumbers: z.boolean().default(true),
  ligatures: z.boolean().default(false),
  terminalFontSize: z.number().int().min(11).max(20).default(12),
})
export type Appearance = z.infer<typeof appearanceSchema>
export const DEFAULT_APPEARANCE: Appearance = appearanceSchema.parse({})
export const APPEARANCE_KEY = 'pw-appearance-v1'
const envelope = z.object({ version: z.literal(1), preferences: appearanceSchema })

interface AppearanceState {
  preferences: Appearance
  open: boolean
  error: string | null
  hydrated: boolean
  setOpen: (open: boolean) => void
  hydrate: () => void
  update: (patch: Partial<Appearance>) => void
  reset: () => void
}

/** 外观仅保存在当前浏览器，与服务器 AI 偏好及项目布局分开。 */
export const useAppearanceStore = create<AppearanceState>((set, get) => {
  const save = (preferences: Appearance) => {
    try {
      localStorage.setItem(APPEARANCE_KEY, JSON.stringify({ version: 1, preferences }))
      set({ preferences, error: null })
    } catch {
      set({ preferences, error: '浏览器未能保存外观设置；当前调整已生效，刷新后可能丢失。' })
    }
  }
  return {
    preferences: { ...DEFAULT_APPEARANCE }, open: false, error: null, hydrated: false,
    setOpen: (open) => set({ open }),
    hydrate: () => {
      if (get().hydrated) return
      try {
        const raw = localStorage.getItem(APPEARANCE_KEY)
        if (raw && raw.length > 10_000) throw new Error('设置过大')
        const preferences = raw ? envelope.parse(JSON.parse(raw)).preferences : { ...DEFAULT_APPEARANCE }
        set({ preferences, error: null, hydrated: true })
      } catch {
        set({ preferences: { ...DEFAULT_APPEARANCE }, error: '外观设置无法读取，已使用默认外观。可重新调整或恢复默认。', hydrated: true })
      }
    },
    update: (patch) => {
      const result = appearanceSchema.safeParse({ ...get().preferences, ...patch })
      if (!result.success) { set({ error: '外观选项无效，请在允许范围内调整。' }); return }
      save(result.data)
    },
    reset: () => save({ ...DEFAULT_APPEARANCE }),
  }
})
