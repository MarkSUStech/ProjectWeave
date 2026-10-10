import type { ReactNode } from 'react'
import { Tabs, TabsList, TabsTrigger, TabsContent } from './upstream/tabs'

/** 工作区页签共用 Radix 的方向键、焦点管理与选中语义。 */
export function PanelTabs<T extends string>({ value, onChange, items, label, children }: {
  value: T; onChange: (value: T) => void; items: readonly { id: T; label: string }[]; label: string; children: ReactNode
}) {
  return <Tabs value={value} onValueChange={(next) => onChange(next as T)} className="h-full min-h-0 flex-1 gap-0">
    <TabsList aria-label={label} variant="line" className="h-12 w-full shrink-0 justify-start gap-1 border-b border-edge-soft px-3">
      {items.map((item) => <TabsTrigger key={item.id} value={item.id} className="h-9 flex-none px-3 text-xs">{item.label}</TabsTrigger>)}
    </TabsList>
    <TabsContent value={value} className="flex min-h-0 flex-1 flex-col">{children}</TabsContent>
  </Tabs>
}
