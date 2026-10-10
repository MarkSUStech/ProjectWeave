/**
 * Scene Renderer（§9.1 L2 组合协议）：按场景描述查注册表渲染组件。
 * - 未注册组件 / 场景 schema 不合法 → 显式错误面板，不静默伪装；
 * - 场景头部展示数据来源标签（真实执行/静态结构/概念模拟，§9.2）；
 * - 交互由组件本地处理（不调 LLM）。
 */
import { SOURCE_LABELS, teachingSceneSchema, type TeachingScene } from './sceneSchema'
import { getComponent } from './registry'
import { ensureBuiltinComponents } from './builtinComponents'
import { Badge } from '../components/ui/Badge'

const SOURCE_TONES = {
  runtime: 'ok',
  static: 'info',
  conceptual: 'warn',
} as const

export function SceneRenderer({ scene }: { scene: unknown }) {
  ensureBuiltinComponents()

  const parsed = teachingSceneSchema.safeParse(scene)
  if (!parsed.success) {
    return (
      <SceneError
        title="场景描述不合法"
        detail={parsed.error.issues.map((i) => `${i.path.join('.')}: ${i.message}`).join('；')}
      />
    )
  }
  const valid = parsed.data as TeachingScene

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex shrink-0 items-center justify-between gap-2 border-b border-edge-soft bg-panel px-3 py-1.5">
        <span className="truncate font-mono text-[11px] text-ink-dim" title={valid.templateId}>
          {valid.templateId}
        </span>
        <div className="flex shrink-0 items-center gap-1.5">
          {valid.allowedInteractions.map((interaction) => (
            <span key={interaction} className="text-[10px] text-ink-faint">
              {interaction}
            </span>
          ))}
          <Badge tone={SOURCE_TONES[valid.sourceType]}>{SOURCE_LABELS[valid.sourceType]}</Badge>
        </div>
      </header>
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {valid.components.map((component) => {
          const meta = getComponent(component.type)
          if (!meta) {
            return (
              <SceneError
                key={component.id}
                title={`未注册的可视化组件：${component.type}`}
                detail="场景引用了组件注册表中不存在的组件；这通常意味着需要新版本前端。"
              />
            )
          }
          const View = meta.View
          // L2 组合（§9.1）：多组件纵向平分画布，共享同一场景数据绑定。
          const areaClass =
            valid.components.length > 1
              ? 'min-h-0 flex-1 border-b border-edge-soft last:border-b-0'
              : 'min-h-0 flex-1 overflow-hidden'
          return (
            <div key={component.id} className={areaClass}>
              <View instanceId={component.id} config={component.config} />
            </div>
          )
        })}
      </div>
    </div>
  )
}

function SceneError({ title, detail }: { title: string; detail: string }) {
  return (
    <div role="alert" className="m-3 rounded border border-danger/40 bg-danger/10 p-3 text-xs">
      <div className="mb-1 font-medium text-danger">{title}</div>
      <p className="leading-relaxed text-ink-dim">{detail}</p>
    </div>
  )
}
