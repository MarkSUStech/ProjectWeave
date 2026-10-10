/**
 * L1 标准组件：变量状态面板（variables-state）。
 *
 * 数据绑定 run:observations —— 渲染 observe(name, value) 上报的真实执行
 * 数据（runtime 来源）。按变量名分组显示当前值与变化序列（本地交互展开，
 * 零 LLM 调用，§9.4"代码 → 图"的教学通道）。
 */
import { Fragment, useMemo, useState } from 'react'
import { useRunStore } from '../../stores/runStore'
import type { Observation } from '../../types/runner'

const MAX_PER_VARIABLE = 20

export function VariablesStateView({ config }: { instanceId: string; config: Record<string, unknown> }) {
  const observations = useRunStore((state) => state.observations)
  const [expanded, setExpanded] = useState<string | null>(null)
  const maxPerVariable =
    typeof config.maxPerVariable === 'number' ? config.maxPerVariable : MAX_PER_VARIABLE

  const grouped = useMemo(() => {
    const map = new Map<string, Observation[]>()
    for (const observation of observations) {
      const list = map.get(observation.name) ?? []
      list.push(observation)
      map.set(observation.name, list)
    }
    // 每变量保留最近 N 次；变量按名字排序保证稳定展示
    return [...map.entries()]
      .map(([name, list]) => ({ name, list: list.slice(-maxPerVariable) }))
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [observations, maxPerVariable])

  if (grouped.length === 0) {
    return (
      <div className="flex h-full items-center justify-center p-4 text-center text-xs leading-relaxed text-ink-faint">
        还没有观察数据。在代码中调用{' '}
        <code className="mx-1 rounded bg-panel-2 px-1.5 py-0.5 font-mono text-[11px] text-accent">
          observe(&#39;变量名&#39;, 变量)
        </code>
        ，运行后这里会显示它的真实值变化。
      </div>
    )
  }

  return (
    <div className="h-full overflow-y-auto p-3" data-testid="variables-state">
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr className="border-b border-edge-soft text-left text-[11px] text-ink-faint">
            <th className="pb-1.5 pr-3 font-medium">变量</th>
            <th className="pb-1.5 pr-3 font-medium">当前值</th>
            <th className="pb-1.5 font-medium">变化</th>
          </tr>
        </thead>
        <tbody>
          {grouped.map(({ name, list }) => {
            const current = list[list.length - 1]
            const isOpen = expanded === name
            const changedBefore = list.length > 1 && list.some((o) => o.value !== current.value)
            return (
              <Fragment key={name}>
                <tr
                  className={`border-b border-edge-soft/60 ${list.length > 1 ? 'cursor-pointer hover:bg-panel-2/60' : ''}`}
                  onClick={() => list.length > 1 && setExpanded(isOpen ? null : name)}
                >
                  <td className="py-1.5 pr-3 font-mono text-accent">{name}</td>
                  <td className="py-1.5 pr-3 font-mono text-ink-dim">
                    <span className="line-clamp-2 break-all" title={current.value}>
                      {current.value}
                    </span>
                    {changedBefore && !isOpen && (
                      <span className="ml-1 text-[10px] text-ink-faint">(有变化，点击展开)</span>
                    )}
                  </td>
                  <td className="py-1.5 text-ink-faint">{list.length} 次</td>
                </tr>
                {isOpen && (
                  <tr className="border-b border-edge-soft/60 bg-panel-2/40">
                    <td colSpan={3} className="px-3 py-2">
                      <ol className="space-y-1 font-mono text-[11px] text-ink-faint">
                        {list.map((observation, index) => (
                          <li key={observation.id} className="flex gap-2">
                            <span className="w-10 shrink-0 text-right">#{index + 1}</span>
                            <span className="break-all text-ink-dim">{observation.value}</span>
                          </li>
                        ))}
                      </ol>
                    </td>
                  </tr>
                )}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
