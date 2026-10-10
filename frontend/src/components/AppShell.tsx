import { Link, useLocation } from 'react-router-dom'
import { FolderKanban, Network, ArrowUpRight, ChevronRight, Monitor } from 'lucide-react'
import type { ReactNode } from 'react'
import { SettingsButton } from './settings/SettingsButton'

/** 主导航保持真实路由，工作台与教学区共享品牌层级。 */
export function AppShell({ children }: { children: ReactNode }) {
  const { pathname } = useLocation()
  const concepts = pathname === '/concepts'
  return <div className="page-surface flex h-dvh overflow-clip bg-app">
    <aside className="app-sidebar hidden h-full w-[216px] shrink-0 flex-col overflow-y-auto overscroll-contain border-r border-edge-soft px-4 py-7 md:flex">
      <Link to="/" className="mb-10 flex items-center gap-3 px-2 text-[15px] font-semibold tracking-tight">
        <svg viewBox="0 0 28 28" aria-hidden="true" className="size-8 text-accent"><path d="M3 7h9l4 14h9M3 21h9l4-14h9" fill="none" stroke="currentColor" strokeWidth="3" strokeLinejoin="round" strokeLinecap="round" /></svg>
        ProjectWeave
      </Link>
      <nav aria-label="主导航" className="space-y-1.5">
        {[{ to: '/', label: '项目工作台', icon: FolderKanban, active: !concepts }, { to: '/concepts', label: '知识图谱', icon: Network, active: concepts }].map(({ to, label, icon: Icon, active }) =>
          <Link key={to} to={to} aria-current={active ? 'page' : undefined} className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-[13px] transition-colors ${active ? 'bg-panel-2 text-ink' : 'text-ink-faint hover:bg-panel-2/70 hover:text-ink'}`}>
            <Icon className={`size-4 ${active ? 'text-accent' : ''}`} />{label}
            {active && <span className="ml-auto size-1 rounded-full bg-accent" />}
          </Link>)}
      </nav>
      <div className="mt-auto border-t border-edge-soft px-2 pt-5">
        <div className="mb-3 flex items-center gap-2 text-xs text-ink-dim"><Monitor className="size-3.5" />浏览器工作区</div>
        <p className="mb-5 text-xs leading-6 text-ink-faint">每一次运行，都是理解代码的新证据。</p>
        <a href="/licenses/NOTICE.txt" target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[11px] text-ink-faint hover:text-ink">开源组件声明<ArrowUpRight className="size-3" /></a>
      </div>
    </aside>
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <header className="flex h-16 shrink-0 items-center justify-between border-b border-edge-soft px-6 lg:px-10">
        <div className="flex items-center gap-2 text-xs text-ink-faint"><Link to="/" className="hover:text-ink">ProjectWeave</Link><ChevronRight className="size-3" /><span className="text-ink-dim">{concepts ? '知识图谱' : '项目工作区'}</span></div>
        <div className="flex items-center gap-3"><Link to={concepts ? '/' : '/concepts'} className="flex items-center gap-2 text-xs text-ink-dim hover:text-ink">{concepts ? '返回工作台' : '探索知识图谱'}<ArrowUpRight className="size-3.5" /></Link><SettingsButton /></div>
      </header>
      <div role="region" aria-label="页面内容" tabIndex={0} className="app-page-content min-h-0 flex-1 overflow-y-auto overscroll-contain">
        {children}
      </div>
    </div>
  </div>
}
