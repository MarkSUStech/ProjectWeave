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

/** 变量状态单组件场景（实验模式主画布）。 */
export const VARIABLES_STATE_SCENE: TeachingScene = {
  sceneId: 'builtin:variables-state',
  templateId: 'runtime.variables-state.v1',
  objectiveId: null,
  sourceType: 'runtime',
  dataBinding: { ref: 'run:observations' },
  components: [
    {
      id: 'variables',
      type: 'variables-state',
      config: {},
    },
  ],
  allowedInteractions: ['点击变量展开变化序列'],
}

/**
 * L2 组合场景（§9.1）：时间线 + 变量状态共享同一批真实运行数据，
 * 支撑"输出 ↔ 状态"对照教学（附录 B M2：解释状态与 DOM 的区别）。
 */
export const DEBUG_PANEL_SCENE: TeachingScene = {
  sceneId: 'builtin:debug-panel',
  templateId: 'runtime.debug-panel.v1',
  objectiveId: null,
  sourceType: 'runtime',
  dataBinding: { ref: 'run:latest' },
  components: [
    {
      id: 'timeline',
      type: 'console-timeline',
      config: { maxEntries: 30 },
    },
    {
      id: 'variables',
      type: 'variables-state',
      config: {},
    },
  ],
  allowedInteractions: ['点击条目查看详情', '点击变量展开变化序列'],
}

/** 真实调试快照场景（P4.5a）：调试模式/会话期间的教学画布。
 * 数据全部来自 LLDB DAP 会话（debug:latest），非 AI 推测。 */
export const DEBUG_SNAPSHOT_SCENE: TeachingScene = {
  sceneId: 'builtin:debug-snapshot',
  templateId: 'runtime.debug-snapshot.v1',
  objectiveId: null,
  sourceType: 'runtime',
  dataBinding: { ref: 'debug:latest' },
  components: [
    { id: 'snapshot', type: 'debug-snapshot', config: { maxFrames: 8 } },
  ],
  allowedInteractions: ['点击选中调用栈帧'],
}
