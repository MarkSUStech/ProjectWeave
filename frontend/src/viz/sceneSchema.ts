/**
 * TeachingScene Schema（设计文档 §9.2/§9.5，Visual Interaction Engine）。
 *
 * 场景是结构化描述（L2 组合协议），不是每次让 LLM 生成新的 React 代码（L3
 * 仅在标准组件无法满足时按需触发——当前未实现，界面如实标注）。
 * 数据来源三分类（§9.2）：runtime（真实执行）/ static（静态结构）/
 * conceptual（概念模拟），UI 必须展示来源标签，禁止把概念模拟冒充真实执行。
 */
import { z } from 'zod'

export const sourceTypeSchema = z.enum(['runtime', 'static', 'conceptual'])

export const SOURCE_LABELS: Record<SourceType, string> = {
  runtime: '真实执行',
  static: '静态结构',
  conceptual: '概念模拟',
}

export const sceneComponentSchema = z.object({
  /** 场景内组件实例 id（渲染 key）。 */
  id: z.string().min(1),
  /** 组件注册表中的 componentId（如 "console-timeline"）。 */
  type: z.string().min(1),
  /** 组件配置（由组件自身的 inputSchema 解释）。 */
  config: z.record(z.string(), z.unknown()).default({}),
})

export const teachingSceneSchema = z.object({
  sceneId: z.string().min(1),
  /** 场景模板版本化 id，如 "runtime.console-timeline.v1"。 */
  templateId: z.string().min(1),
  /** 关联的教学目标（概念 id，可为空——工具型场景无单一目标）。 */
  objectiveId: z.string().nullable().default(null),
  sourceType: sourceTypeSchema,
  /**
   * 数据绑定引用（§9.2）：如 "run:latest"。组件据此自行解析数据；
   * runtime 场景必须绑定真实执行数据，解析失败显示"需要重新运行"。
   */
  dataBinding: z.record(z.string(), z.unknown()).default({}),
  components: z.array(sceneComponentSchema).min(1),
  /** 允许的本地交互（渲染层处理，不调 LLM，§9.1）。 */
  allowedInteractions: z.array(z.string()).default([]),
})

export type SourceType = z.infer<typeof sourceTypeSchema>
export type SceneComponent = z.infer<typeof sceneComponentSchema>
export type TeachingScene = z.infer<typeof teachingSceneSchema>
