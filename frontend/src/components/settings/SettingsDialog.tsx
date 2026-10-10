import { useEffect, useId, useState, type ReactNode } from 'react'
import { RadioGroup, Tabs, Switch } from 'radix-ui'
import { Palette, Code2, PanelsTopLeft, RotateCcw, Check, LockKeyhole } from 'lucide-react'
import { useAppearanceStore, type Appearance } from '../../stores/appearanceStore'
import { useIdeUiStore } from '../../stores/ideUiStore'
import { useWorkspaceLayout } from '../ide/WorkspaceLayoutContext'
import { WORKSPACE_PANELS } from '../../lib/dockLayout'
import { THEME_PALETTES } from '../../lib/appearance'
import { cn } from '../../lib/utils'
import { Button } from '../ui/Button'
import { Dialog, DialogTrigger, DialogContent, DialogTitle, DialogDescription } from '../ui/upstream/dialog'

function SettingRow({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return <div className="flex flex-col items-stretch justify-between gap-3 border-b border-edge-soft py-4 last:border-0 sm:flex-row sm:flex-wrap sm:items-center sm:gap-4">
    <div className="min-w-0 flex-1"><p className="text-sm font-medium">{title}</p>{description && <p className="mt-1 text-pretty text-xs leading-5 text-ink-faint">{description}</p>}</div>{children}
  </div>
}
function AccentInput({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const [draft, setDraft] = useState(value)
  useEffect(() => { setDraft(value) }, [value])
  return <input aria-label="强调色十六进制值" value={draft} maxLength={7} spellCheck={false}
    className="w-20 rounded-md border border-edge bg-app px-2 py-1.5 font-mono text-[11px]"
    onChange={(e) => { const next = e.target.value; setDraft(next); if (/^#[0-9a-fA-F]{6}$/.test(next)) onChange(next) }}
    onBlur={() => setDraft(value)} />
}
function Toggle({ label, value, onChange, disabled = false }: { label: string; value: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return <Switch.Root aria-label={label} checked={value} onCheckedChange={onChange} disabled={disabled}
    className="inline-flex h-6 w-11 shrink-0 items-center rounded-full border border-edge bg-panel-2 px-0.5 data-[state=checked]:border-accent data-[state=checked]:bg-accent disabled:opacity-40">
    <Switch.Thumb className="block size-4 rounded-full bg-ink-faint data-[state=checked]:translate-x-5 data-[state=checked]:bg-primary-foreground" />
  </Switch.Root>
}
function Range({ label, value, min, max, step = 1, suffix = '', onChange }: { label: string; value: number; min: number; max: number; step?: number; suffix?: string; onChange: (v: number) => void }) {
  const id = useId()
  return <div className="flex w-52 max-w-full items-center gap-3">
    <label className="sr-only" htmlFor={id}>{label}</label>
    <input id={id} className="h-5 min-w-0 flex-1 accent-accent" type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} aria-valuetext={`${value}${suffix}`} />
    <output htmlFor={id} className="w-12 text-right text-xs tabular-nums text-ink-dim">{value}{suffix}</output>
  </div>
}
function Choices<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: { value: T; label: string }[]; onChange: (v: T) => void }) {
  return <RadioGroup.Root aria-label={label} value={value} onValueChange={(v) => onChange(v as T)} className="flex flex-wrap gap-1 rounded-lg border border-edge-soft bg-app p-1">
    {options.map((option) => <RadioGroup.Item key={option.value} value={option.value} className="rounded-md px-3 py-1.5 text-xs text-ink-faint data-[state=checked]:bg-panel-2 data-[state=checked]:text-ink">{option.label}</RadioGroup.Item>)}
  </RadioGroup.Root>
}

/** 全站同一设置面板；在工作区内挂载时同时获得真实布局控制器。 */
export function SettingsDialog({ trigger }: { trigger?: ReactNode }) {
  const { preferences: p, update, reset, open, setOpen, error } = useAppearanceStore()
  const { locked, toggleLock } = useIdeUiStore()
  const layout = useWorkspaceLayout()
  const [tab, setTab] = useState('appearance')
  const set = <K extends keyof Appearance>(key: K, value: Appearance[K]) => update({ [key]: value })
  return <Dialog open={open} onOpenChange={setOpen}>
    {trigger && <DialogTrigger asChild>{trigger}</DialogTrigger>}
    <DialogContent className="settings-dialog flex max-h-[calc(100dvh-2rem)] w-[760px] max-w-[calc(100vw-2rem)] flex-col gap-0 overflow-clip p-0 sm:max-w-[760px]">
      <div className="shrink-0 border-b border-edge-soft px-6 py-5 pr-12">
        <p className="mb-2 text-[10px] font-medium text-accent">PROJECTWEAVE / 你的工作空间</p>
        <DialogTitle className="text-balance text-xl">界面设置</DialogTitle>
        <DialogDescription className="mt-2 text-pretty text-xs leading-5">按你的习惯调整。更改即时生效，外观自动保存在当前浏览器。</DialogDescription>
      </div>
      <Tabs.Root value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col">
        <Tabs.List aria-label="设置分类" className="flex shrink-0 gap-1 border-b border-edge-soft bg-app px-4 py-2 sm:gap-2 sm:px-6">
          {[{ id: 'appearance', label: '外观与动效', icon: Palette }, { id: 'editor', label: '编辑器与终端', icon: Code2 }, { id: 'workspace', label: '工作区布局', icon: PanelsTopLeft }].map(({ id, label, icon: Icon }) =>
            <Tabs.Trigger key={id} value={id} className="inline-flex items-center gap-2 rounded-md px-2 py-2 text-[11px] text-ink-faint data-[state=active]:bg-panel-2 data-[state=active]:text-ink sm:px-3 sm:text-xs"><Icon className="hidden size-3.5 sm:inline-block" />{label}</Tabs.Trigger>)}
        </Tabs.List>
        <div key={tab} className="min-h-0 overflow-y-auto overscroll-contain px-6 pb-3">
          <Tabs.Content value="appearance" className="outline-none">
            <fieldset className="py-5"><legend className="sr-only">主题</legend>
              <RadioGroup.Root aria-label="主题" value={p.theme} onValueChange={(v) => set('theme', v as Appearance['theme'])} className="grid grid-cols-3 gap-2 sm:gap-3">
                {([{ value: 'graphite', label: '石墨灰', caption: '克制 · 专注' }, { value: 'midnight', label: '午夜蓝', caption: '沉静 · 清晰' }, { value: 'paper', label: '浅色纸张', caption: '明亮 · 轻盈' }] as const).map(({ value, label, caption }) => {
                  const c = THEME_PALETTES[value]
                  return <RadioGroup.Item key={value} value={value} aria-label={label} className={cn('overflow-hidden rounded-lg border text-left', p.theme === value ? 'border-accent ring-1 ring-accent' : 'border-edge')}>
                    <span className="flex h-20 gap-1.5 p-3" style={{ background: c.app }}><span className="w-1/4 rounded-sm" style={{ background: c.raised }} /><span className="flex flex-1 flex-col gap-1.5 rounded-sm p-2" style={{ background: c.panel }}><span className="h-1 w-1/2 rounded-full" style={{ background: p.accent }} /><span className="h-1 w-4/5 rounded-full" style={{ background: c.edge }} /><span className="h-1 w-3/5 rounded-full" style={{ background: c.edge }} /></span></span>
                    <span className="flex items-center justify-between gap-1 px-2 py-2.5 sm:px-3"><span><span className="block whitespace-nowrap text-[10px] font-medium sm:text-xs">{label}</span><span className="mt-1 hidden text-[10px] text-ink-faint sm:block">{caption}</span></span>{p.theme === value && <Check className="size-3 shrink-0 text-accent sm:size-3.5" />}</span>
                  </RadioGroup.Item>
                })}
              </RadioGroup.Root>
            </fieldset>
            <SettingRow title="强调色" description="主按钮、焦点、选中状态与代码光标同步变化。">
              <div className="flex flex-wrap items-center gap-2">
                {[{ color: '#c1b5ff', label: '柔紫' }, { color: '#80c7ef', label: '天蓝' }, { color: '#83d5a6', label: '薄荷' }, { color: '#e8bf6a', label: '琥珀' }, { color: '#ed9daf', label: '玫瑰' }].map(({ color, label }) => <button key={color} type="button" aria-label={`强调色：${label}`} aria-pressed={p.accent.toLowerCase() === color} onClick={() => set('accent', color)} className="grid size-6 place-items-center rounded-full border border-edge" style={{ background: color }}>{p.accent.toLowerCase() === color && <Check className="size-3.5 text-[#151517]" />}</button>)}
                <label className="ml-1 flex items-center gap-1 text-[10px] text-ink-faint">自定<input aria-label="自定义强调色" type="color" value={p.accent} onChange={(e) => set('accent', e.target.value)} className="size-7 cursor-pointer rounded border border-edge bg-panel p-0.5" /></label>
                <AccentInput value={p.accent} onChange={(value) => set('accent', value)} />
              </div>
            </SettingRow>
            <SettingRow title="界面字号" description="调整使用相对尺寸的文字和控件；代码字号独立设置。"><Range label="界面字号" value={p.uiScale} min={90} max={120} step={5} suffix="%" onChange={(v) => set('uiScale', v)} /></SettingRow>
            <SettingRow title="界面密度" description="按钮、导航与面板标题栏的间距。"><Choices label="界面密度" value={p.density} onChange={(v) => set('density', v)} options={[{ value: 'compact', label: '紧凑' }, { value: 'comfortable', label: '适中' }, { value: 'spacious', label: '宽松' }]} /></SettingRow>
            <SettingRow title="圆角大小"><Range label="圆角大小" value={p.radius} min={0} max={16} suffix="px" onChange={(v) => set('radius', v)} /></SettingRow>
            <SettingRow title="页面背景" description="用于工作台和知识页，代码区保持清晰。"><Choices label="页面背景" value={p.texture} onChange={(v) => set('texture', v)} options={[{ value: 'none', label: '纯色' }, { value: 'dots', label: '点阵' }, { value: 'grid', label: '网格' }]} /></SettingRow>
            <SettingRow title="卡片阴影"><Toggle label="卡片阴影" value={p.shadows} onChange={(v) => set('shadows', v)} /></SettingRow>
            <SettingRow title="界面动效" description="页面、卡片、模式与展开效果；开启时仍尊重系统减少动态效果偏好。"><Toggle label="界面动效" value={p.motion} onChange={(v) => set('motion', v)} /></SettingRow>
          </Tabs.Content>
          <Tabs.Content value="editor" className="outline-none">
            <SettingRow title="代码字体" description="使用设备已安装的字体；缺少所选字体时自动回退。"><label className="sr-only" htmlFor="code-font">代码字体</label><select id="code-font" value={p.editorFont} onChange={(e) => set('editorFont', e.target.value as Appearance['editorFont'])} className="rounded-md border border-edge bg-app px-3 py-2 text-xs"><option value="cascadia">Cascadia Code</option><option value="jetbrains">JetBrains Mono</option><option value="system">系统等宽字体</option></select></SettingRow>
            <SettingRow title="代码字号"><Range label="代码字号" value={p.editorFontSize} min={11} max={22} suffix="px" onChange={(v) => set('editorFontSize', v)} /></SettingRow>
            <SettingRow title="代码行高"><Range label="代码行高" value={p.editorLineHeight} min={1.3} max={2} step={0.05} suffix="×" onChange={(v) => set('editorLineHeight', v)} /></SettingRow>
            <SettingRow title="自动换行"><Toggle label="自动换行" value={p.wordWrap} onChange={(v) => set('wordWrap', v)} /></SettingRow>
            <SettingRow title="显示行号"><Toggle label="显示行号" value={p.lineNumbers} onChange={(v) => set('lineNumbers', v)} /></SettingRow>
            <SettingRow title="显示代码缩略图"><Toggle label="显示代码缩略图" value={p.minimap} onChange={(v) => set('minimap', v)} /></SettingRow>
            <SettingRow title="字体连字" description="需要所选字体支持连字。"><Toggle label="字体连字" value={p.ligatures} onChange={(v) => set('ligatures', v)} /></SettingRow>
            <SettingRow title="终端字号" description="实际运行输出使用相同等宽字体。"><Range label="终端字号" value={p.terminalFontSize} min={11} max={20} suffix="px" onChange={(v) => set('terminalFontSize', v)} /></SettingRow>
            <div className="my-4 rounded-lg border border-edge-soft bg-editor p-4" aria-label="代码字号预览" style={{ fontSize: p.editorFontSize, lineHeight: p.editorLineHeight }}><code className="font-mono"><span className="text-accent">const</span> workspace = <span className="text-ok">'你的工作空间'</span>;</code><p className="mt-2 text-xs text-ink-faint">预览样式 · 当前编辑内容不会被替换</p></div>
          </Tabs.Content>
          <Tabs.Content value="workspace" className="outline-none">
            <SettingRow title="锁定布局" description="锁定后拒绝移动、缩放、隐藏与模式切换；仍可编辑和运行。"><Toggle label="锁定布局" value={locked} onChange={() => toggleLock()} /></SettingRow>
            {locked && <p className="mt-3 flex items-center gap-2 text-xs text-warn"><LockKeyhole className="size-3.5" />解锁后可以调整工作区布局。</p>}
            {layout ? <><fieldset className="py-5"><legend className="pt-5 text-sm font-medium">显示的面板</legend><div className="grid grid-cols-2 gap-x-6 sm:grid-cols-3">{WORKSPACE_PANELS.map(({ id, title }) => <div key={id} className="flex items-center justify-between gap-3 py-3"><span className="text-xs text-ink-dim">{title}</span><Toggle label={`显示${title}`} disabled={locked} value={layout.visible.includes(id)} onChange={(v) => v ? layout.reveal(id) : layout.hide(id)} /></div>)}</div></fieldset><Button variant="outline" size="sm" disabled={locked} onClick={layout.reset}><RotateCcw className="size-3.5" />恢复当前模式默认布局</Button></> : <p className="py-6 text-pretty text-sm leading-6 text-ink-dim">进入项目的教学工作区后，可在这里显示/隐藏面板和恢复布局。</p>}
            <p className="my-5 rounded-lg border border-edge-soft bg-app p-4 text-pretty text-xs leading-6 text-ink-faint">拖动面板标题到边缘拆分，到中央合并；面板菜单可移动到四边或在工作区内悬浮。布局按项目、按模式分别保存。</p>
          </Tabs.Content>
        </div>
      </Tabs.Root>
      <footer className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-edge-soft bg-app px-6 py-4">
        <p role={error ? 'alert' : 'status'} className={cn('min-w-0 flex-1 text-xs', error ? 'text-danger' : 'text-ink-faint')}>{error ?? '即时生效 · 自动保存在此浏览器'}</p>
        <Button variant="ghost" size="sm" onClick={reset}><RotateCcw className="size-3.5" />恢复默认外观</Button>
      </footer>
    </DialogContent>
  </Dialog>
}
