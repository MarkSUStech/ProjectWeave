/** P8.1 CMake 控件测试：目标发现 → 选择 → 构建/运行/测试触发（mock 后端调用）。 */

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

vi.mock('../lib/runner/runCmake', () => ({
  cmakeDiscoverInTerminal: vi.fn(),
  cmakeBuildInTerminal: vi.fn(),
  cmakeRunInTerminal: vi.fn(),
  cmakeTestInTerminal: vi.fn(),
}))

import { CMakeControls } from '../components/ide/CMakeControls'
import {
  cmakeBuildInTerminal,
  cmakeDiscoverInTerminal,
  cmakeRunInTerminal,
  cmakeTestInTerminal,
} from '../lib/runner/runCmake'

const FILES = [
  { path: 'CMakeLists.txt', size: 100, updatedAt: '2026-10-12T00:00:00Z' },
  { path: 'game/main.cpp', size: 100, updatedAt: '2026-10-12T00:00:00Z' },
]

const TARGETS = [
  {
    name: 'engine', type: 'STATIC_LIBRARY', runnable: false,
    sourceDirectory: 'engine', buildDirectory: 'build/engine',
    sources: [], artifacts: [], dependencies: [], configuration: 'Debug',
  },
  {
    name: 'game', type: 'EXECUTABLE', runnable: true,
    sourceDirectory: 'game', buildDirectory: 'build/game',
    sources: ['game/main.cpp'], artifacts: ['build/game/game'],
    dependencies: ['engine'], configuration: 'Debug',
  },
]

const vfs = new Map([['CMakeLists.txt', '']])
const buildVfs = async () => vfs

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(cmakeDiscoverInTerminal).mockResolvedValue({
    ok: true, exitCode: 0, executionId: 'e1', targets: TARGETS,
    discoveredTests: [], testResults: [], cmakeVersion: 'cmake version 3.25.1', generator: 'Ninja',
  })
  vi.mocked(cmakeBuildInTerminal).mockResolvedValue({
    ok: true, exitCode: 0, executionId: 'e2', targets: [], discoveredTests: [], testResults: [], cmakeVersion: null, generator: null,
  })
  vi.mocked(cmakeRunInTerminal).mockResolvedValue({
    ok: true, exitCode: 0, executionId: 'e3', targets: [], discoveredTests: [], testResults: [], cmakeVersion: null, generator: null,
  })
  vi.mocked(cmakeTestInTerminal).mockResolvedValue({
    ok: false, exitCode: 1, executionId: 'e4', targets: [], discoveredTests: ['test_world'], testResults: [], cmakeVersion: null, generator: null,
  })
})

describe('CMakeControls', () => {
  it('非 CMake 项目不渲染', () => {
    const { container } = render(
      <CMakeControls projectId="p1" files={[{ path: 'main.py', size: 10, updatedAt: '' }]} buildVfs={buildVfs} onRevealTerminal={() => {}} />,
    )
    expect(container.innerHTML).toBe('')
  })

  it('Configure 后填充真实目标；选择目标并触发构建与运行', async () => {
    render(<CMakeControls projectId="p1" files={FILES} buildVfs={buildVfs} onRevealTerminal={() => {}} />)

    // 初始：未发现目标的占位 + Configure 按钮
    expect(screen.getByText('Configure')).toBeTruthy()
    expect(screen.getByText(/未发现目标/)).toBeTruthy()

    fireEvent.click(screen.getByText('Configure'))
    await waitFor(() => expect(cmakeDiscoverInTerminal).toHaveBeenCalledWith(vfs, 'p1'))
    await waitFor(() => expect(screen.getByText(/cmake version 3\.25\.1/)).toBeTruthy())

    // 默认选中第一个可运行目标（game 排在库目标前）
    const selector = screen.getByLabelText('选择 CMake 目标') as HTMLSelectElement
    expect(selector.value).toBe('game')
    expect(screen.getByText(/链接：engine/)).toBeTruthy()

    fireEvent.click(screen.getByText('构建目标'))
    await waitFor(() => expect(cmakeBuildInTerminal).toHaveBeenCalledWith(vfs, 'game', 'p1'))

    fireEvent.click(screen.getByText('运行目标'))
    await waitFor(() => expect(cmakeRunInTerminal).toHaveBeenCalledWith(vfs, 'game', 'p1'))

    fireEvent.click(screen.getByText(/运行测试（CTest）/))
    await waitFor(() => expect(cmakeTestInTerminal).toHaveBeenCalledWith(vfs, 'p1'))
  })

  it('选中库目标时运行按钮禁用（library 不可当 executable）', async () => {
    render(<CMakeControls projectId="p1" files={FILES} buildVfs={buildVfs} onRevealTerminal={() => {}} />)
    fireEvent.click(screen.getByText('Configure'))
    await waitFor(() => expect(screen.getByLabelText('选择 CMake 目标')).toBeTruthy())

    fireEvent.change(screen.getByLabelText('选择 CMake 目标'), { target: { value: 'engine' } })
    const runButton = screen.getByText('运行目标').closest('button') as HTMLButtonElement
    expect(runButton.disabled).toBe(true)
    // 构建库目标仍然允许
    expect((screen.getByText('构建目标').closest('button') as HTMLButtonElement).disabled).toBe(false)
  })
})
