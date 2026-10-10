/** useProjectFiles hook 测试：加载、脏状态、保存、切换保护、文件操作、自动保存。 */
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useProjectFiles } from '../hooks/useProjectFiles'
import type { FileMeta } from '../types/file'

vi.mock('../api/files', () => ({
  listFiles: vi.fn(),
  readFile: vi.fn(),
  writeFile: vi.fn(),
  renameFile: vi.fn(),
  deleteFile: vi.fn(),
}))

const { listFiles, readFile, writeFile, renameFile, deleteFile } = await import('../api/files')
const mocked = {
  list: vi.mocked(listFiles),
  read: vi.mocked(readFile),
  write: vi.mocked(writeFile),
  rename: vi.mocked(renameFile),
  remove: vi.mocked(deleteFile),
}

const readmeMeta: FileMeta = { path: 'README.md', size: 10, updatedAt: '2026-10-10T04:00:00Z' }
const mainMeta: FileMeta = { path: 'src/main.ts', size: 20, updatedAt: '2026-10-10T04:00:00Z' }

function setup() {
  return renderHook(() => useProjectFiles('project-1'))
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.restoreAllMocks()
})

describe('useProjectFiles', () => {
  it('加载文件树并默认打开 README.md', async () => {
    mocked.list.mockResolvedValue([readmeMeta, mainMeta])
    mocked.read.mockResolvedValue({ path: 'README.md', content: '# 标题', updatedAt: 't' })

    const { result } = setup()
    await waitFor(() => expect(result.current.files).not.toBeNull())
    expect(result.current.openPath).toBe('README.md')
    expect(result.current.draftContent).toBe('# 标题')
    expect(result.current.dirty).toBe(false)
  })

  it('编辑后 dirty 为真，保存后恢复并更新文件元数据', async () => {
    mocked.list.mockResolvedValue([readmeMeta])
    mocked.read.mockResolvedValue({ path: 'README.md', content: 'v1', updatedAt: 't' })
    const { result } = setup()
    await waitFor(() => expect(result.current.openPath).toBe('README.md'))

    act(() => result.current.setDraft('v2'))
    expect(result.current.dirty).toBe(true)

    mocked.write.mockResolvedValue({ ...readmeMeta, size: 2, updatedAt: 't2' })
    await act(() => result.current.save())
    expect(mocked.write).toHaveBeenCalledWith('project-1', 'README.md', 'v2')
    expect(result.current.dirty).toBe(false)
    expect(result.current.files?.find((f) => f.path === 'README.md')?.size).toBe(2)
  })

  it('内容未变化时保存不发起请求', async () => {
    mocked.list.mockResolvedValue([readmeMeta])
    mocked.read.mockResolvedValue({ path: 'README.md', content: 'same', updatedAt: 't' })
    const { result } = setup()
    await waitFor(() => expect(result.current.openPath).toBe('README.md'))

    await act(() => result.current.save())
    expect(mocked.write).not.toHaveBeenCalled()
  })

  it('有未保存修改时切换文件需要用户确认', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    mocked.list.mockResolvedValue([readmeMeta, mainMeta])
    mocked.read.mockResolvedValue({ path: 'README.md', content: 'draft', updatedAt: 't' })
    const { result } = setup()
    await waitFor(() => expect(result.current.openPath).toBe('README.md'))

    act(() => result.current.setDraft('changed'))
    await act(() => result.current.openFile('src/main.ts'))
    expect(confirmSpy).toHaveBeenCalled()
    expect(result.current.openPath).toBe('README.md') // 拒绝后不切换

    confirmSpy.mockReturnValue(true)
    mocked.read.mockResolvedValue({ path: 'src/main.ts', content: 'code', updatedAt: 't' })
    await act(() => result.current.openFile('src/main.ts'))
    expect(result.current.openPath).toBe('src/main.ts')
    expect(result.current.draftContent).toBe('code')
  })

  it('createFile 写入空文件、刷新列表并打开新文件', async () => {
    mocked.list
      .mockResolvedValueOnce([readmeMeta])
      .mockResolvedValueOnce([readmeMeta, { path: 'new.ts', size: 0, updatedAt: 't' }])
    mocked.read.mockResolvedValue({ path: 'README.md', content: 'x', updatedAt: 't' })
    const { result } = setup()
    await waitFor(() => expect(result.current.files).not.toBeNull())

    mocked.write.mockResolvedValue({ path: 'new.ts', size: 0, updatedAt: 't' })
    mocked.read.mockResolvedValue({ path: 'new.ts', content: '', updatedAt: 't' })
    let ok = false
    await act(async () => {
      ok = await result.current.createFile('new.ts')
    })
    expect(ok).toBe(true)
    expect(mocked.write).toHaveBeenCalledWith('project-1', 'new.ts', '')
    expect(result.current.openPath).toBe('new.ts')
    expect(result.current.files?.map((f) => f.path)).toContain('new.ts')
  })

  it('deleteFile 删除当前打开文件后清空编辑器', async () => {
    mocked.list.mockResolvedValue([readmeMeta])
    mocked.read.mockResolvedValue({ path: 'README.md', content: 'x', updatedAt: 't' })
    const { result } = setup()
    await waitFor(() => expect(result.current.openPath).toBe('README.md'))

    mocked.remove.mockResolvedValue(undefined)
    mocked.list.mockResolvedValue([])
    await act(async () => {
      expect(await result.current.deleteFile('README.md')).toBe(true)
    })
    expect(result.current.openPath).toBeNull()
    expect(result.current.files).toHaveLength(0)
  })

  it('renameFile 更新打开路径并刷新列表', async () => {
    mocked.list.mockResolvedValue([readmeMeta])
    mocked.read.mockResolvedValue({ path: 'README.md', content: 'x', updatedAt: 't' })
    const { result } = setup()
    await waitFor(() => expect(result.current.openPath).toBe('README.md'))

    mocked.rename.mockResolvedValue({ path: 'INTRO.md', size: 1, updatedAt: 't2' })
    mocked.list.mockResolvedValue([{ path: 'INTRO.md', size: 1, updatedAt: 't2' }])
    await act(async () => {
      expect(await result.current.renameFile('README.md', 'INTRO.md')).toBe(true)
    })
    expect(result.current.openPath).toBe('INTRO.md')
    expect(result.current.files?.[0]?.path).toBe('INTRO.md')
  })

  it('列表加载失败时给出错误而不崩溃', async () => {
    mocked.list.mockRejectedValue(new Error('network down'))
    const { result } = setup()
    await waitFor(() => expect(result.current.treeError).not.toBeNull())
    expect(result.current.files).toEqual([])
  })
})

describe('useProjectFiles 自动保存', () => {
  beforeEach(() => {
    vi.useRealTimers()
  })

  async function setupOpened(initial?: Parameters<typeof useProjectFiles>[1]) {
    mocked.list.mockResolvedValue([readmeMeta])
    mocked.read.mockResolvedValue({ path: 'README.md', content: 'v1', updatedAt: 't' })
    const rendered = renderHook(() => useProjectFiles('project-1', initial))
    await waitFor(() => expect(rendered.result.current.openPath).toBe('README.md'))
    return rendered
  }

  it('停止输入 2.5s 后自动保存', async () => {
    const { result } = await setupOpened()
    mocked.write.mockResolvedValue({ ...readmeMeta, size: 2, updatedAt: 't2' })

    vi.useFakeTimers()
    try {
      act(() => result.current.setDraft('auto-v2'))
      expect(result.current.dirty).toBe(true)
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2500)
      })
      expect(mocked.write).toHaveBeenCalledWith('project-1', 'README.md', 'auto-v2')
      expect(result.current.dirty).toBe(false)
    } finally {
      vi.useRealTimers()
    }
  })

  it('持续输入会重置防抖计时器', async () => {
    const { result } = await setupOpened()
    mocked.write.mockResolvedValue({ ...readmeMeta, size: 2, updatedAt: 't2' })

    vi.useFakeTimers()
    try {
      act(() => result.current.setDraft('a'))
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000)
      })
      act(() => result.current.setDraft('ab')) // 2s 时继续输入，重置计时
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000)
      })
      expect(mocked.write).not.toHaveBeenCalled() // 距最后输入仅 2s
      await act(async () => {
        await vi.advanceTimersByTimeAsync(600)
      })
      expect(mocked.write).toHaveBeenCalledWith('project-1', 'README.md', 'ab')
    } finally {
      vi.useRealTimers()
    }
  })

  it('autoSaveMs=null 关闭自动保存', async () => {
    const { result } = await setupOpened({ autoSaveMs: null })
    vi.useFakeTimers()
    try {
      act(() => result.current.setDraft('no-auto'))
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5000)
      })
      expect(mocked.write).not.toHaveBeenCalled()
      expect(result.current.dirty).toBe(true)
    } finally {
      vi.useRealTimers()
    }
  })
})
