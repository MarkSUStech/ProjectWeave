/**
 * 内置标准场景（确定性定义，非 AI 生成）。
 * 场景数据绑定由组件解析；runtime 场景必须来自真实执行数据。
 */
import type { TeachingScene } from './sceneSchema'

export const LATEST_RUN_SCENE: TeachingScene = {
  sceneId: 'builtin:latest-run-timeline',
  templateId: 'runtime.console-timeline.v1',
  objectiveId: null,
  sourceType: 'runtime',
  dataBinding: { ref: 'run:latest' },
  components: [
    {
      id: 'timeline',
      type: 'console-timeline',
      config: { maxEntries: 50 },
    },
  ],
  allowedInteractions: ['点击条目查看详情'],
}
