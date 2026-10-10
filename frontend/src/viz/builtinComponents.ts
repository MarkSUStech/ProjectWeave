/**
 * 内置标准组件登记（L1）。模块导入即完成注册；新组件在此追加。
 * 幂等性以注册表自身为准（测试可清空后重新 ensure）。
 */
import { getComponent, registerComponent } from './registry'
import { ConsoleTimelineView } from './components/consoleTimeline'
import { VariablesStateView } from './components/variablesState'
import { DebugSnapshotView } from './components/debugSnapshot'

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
  registerComponent({
    componentId: 'variables-state',
    version: 'v1',
    supportedConcepts: ['js.objects', 'js.callbacks-events', 'browser.storage'],
    dataSources: ['run:observations'],
    renderCapabilities: ['变量当前值', '变化序列', '多变量对比'],
    accessibilityDescription: '按变量名分组的真实值变化表，点击展开历史序列',
    View: VariablesStateView,
  })
  registerComponent({
    componentId: 'debug-snapshot',
    version: 'v1',
    supportedConcepts: ['cpp.functions', 'cpp.recursion', 'js.functions'],
    dataSources: ['debug:latest'],
    renderCapabilities: ['真实暂停位置', '调用栈', '局部变量与变化'],
    accessibilityDescription: '来自真实 LLDB 调试会话的执行位置、调用栈与变量状态，可点击选中栈帧',
    View: DebugSnapshotView,
  })
}
