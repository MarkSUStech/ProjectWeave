/**
 * 内置标准组件登记（L1）。模块导入即完成注册；新组件在此追加。
 * 幂等性以注册表自身为准（测试可清空后重新 ensure）。
 */
import { getComponent, registerComponent } from './registry'
import { ConsoleTimelineView } from './components/consoleTimeline'

export function ensureBuiltinComponents(): void {
  if (getComponent('console-timeline')) return
  registerComponent({
    componentId: 'console-timeline',
    version: 'v1',
    supportedConcepts: ['js.callbacks-events', 'js.async', 'eng.errors'],
    dataSources: ['run:latest'],
    renderCapabilities: ['执行时间线', '输出级别', '相对时间'],
    accessibilityDescription: '按时间排列的运行输出时间线，点击条目查看详情',
    View: ConsoleTimelineView,
  })
}
