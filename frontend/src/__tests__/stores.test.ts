/** IDE UI 状态测试：布局锁定必须拒绝模式切换（含未来 AI 建议路径）。 */
import { beforeEach, describe, expect, it } from 'vitest'
import { useIdeUiStore } from '../stores/ideUiStore'

beforeEach(() => {
  useIdeUiStore.setState({ mode: 'coding', locked: false })
})

describe('ideUiStore', () => {
  it('未锁定时可以切换工作模式', () => {
    useIdeUiStore.getState().setMode('debugging')
    expect(useIdeUiStore.getState().mode).toBe('debugging')
  })

  it('布局锁定后 setMode 是空操作', () => {
    const store = useIdeUiStore.getState()
    store.toggleLock()
    useIdeUiStore.getState().setMode('visual-learning')
    expect(useIdeUiStore.getState().mode).toBe('coding')
    expect(useIdeUiStore.getState().locked).toBe(true)
  })

  it('解锁后恢复切换能力', () => {
    useIdeUiStore.getState().toggleLock() // 锁定
    useIdeUiStore.getState().toggleLock() // 解锁
    useIdeUiStore.getState().setMode('architecture')
    expect(useIdeUiStore.getState().mode).toBe('architecture')
  })
})
