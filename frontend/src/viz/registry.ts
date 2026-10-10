/**
 * 可视化组件注册表（设计 §9.3）：L1 标准组件在此登记，含元数据与数据来源声明。
 * SceneRenderer 只渲染已注册组件；未注册显式报错，不静默降级伪装。
 */
import type { ComponentType } from 'react'
import type { SceneComponent } from './sceneSchema'

export interface VisualComponentMeta {
  componentId: string
  version: string
  /** 支持的教学概念（供课程/Tutor 检索匹配，§9.3）。 */
  supportedConcepts: string[]
  /** 声明可消费的数据来源（如 'run:latest'）。 */
  dataSources: string[]
  /** 渲染能力标签（教学检索用）。 */
  renderCapabilities: string[]
  /** 无障碍描述。 */
  accessibilityDescription: string
  /** 渲染组件：接收实例 id 与 config，自行解析数据绑定。 */
  View: ComponentType<{ instanceId: string; config: SceneComponent['config'] }>
}

const registry = new Map<string, VisualComponentMeta>()

export function registerComponent(meta: VisualComponentMeta): void {
  if (registry.has(meta.componentId)) {
    throw new Error(`可视化组件重复注册：${meta.componentId}`)
  }
  registry.set(meta.componentId, meta)
}

export function getComponent(componentId: string): VisualComponentMeta | undefined {
  return registry.get(componentId)
}

export function listComponents(): VisualComponentMeta[] {
  return [...registry.values()]
}

export function clearRegistryForTests(): void {
  registry.clear()
}
