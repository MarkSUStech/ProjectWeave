/** useFileHistory 测试：加载、预览切换、恢复与文件切换重载。 */
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useFileHistory } from '../hooks/useFileHistory'
import type { SnapshotMeta } from '../types/file'

vi.mock('../api/files', () => ({
  listFileHistory: vi.fn(),
  readSnapshot: vi.fn(),
  restoreSnapshot: vi.fn(),
}))

const { listFileHistory, readSnapshot, restoreSnapshot } = await import('../api/files')
const mockedList = vi.mocked(listFileHistory)
const mockedRead = vi.mocked(readSnapshot)
const mockedRestore = vi.mocked(restoreSnapshot)

const snapA: SnapshotMeta = {
  id: '11111111-1111-1111-1111-111111111111',
  path: 'a.ts',
  size: 10,
  sha256: 'aaaa',
  createdAt: '2026-10-10T05:00:00Z',
}
const snapB: SnapshotMeta = {
  id: '22222222-2222-2222-2222-222222222222',
  path: 'a.ts',
  size: 20,
  sha256: 'bbbb',
  createdAt: '2026-10-10T06:00:00Z',
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('useFileHistory', () => {
  it('保存后元数据版本变化会重新加载快照，不需要切换文件', async () => {
    mockedList.mockResolvedValueOnce([]).mockResolvedValue([snapA])
    const { result, rerender } = renderHook(({ savedAt }) => useFileHistory('p1', 'a.ts', savedAt), { initialProps: { savedAt: 'v1' } })
    await waitFor(() => expect(result.current.history).toEqual([]))
    rerender({ savedAt: 'v2' })
    await waitFor(() => expect(result.current.history).toEqual([snapA]))
    expect(mockedList).toHaveBeenCalledTimes(2)
  })
  it('openPath 存在时加载历史列表', async () => {
    mockedList.mockResolvedValue([snapB, snapA])
    const { result } = renderHook(() => useFileHistory('p1', 'a.ts'))
    await waitFor(() => expect(result.current.history).not.toBeNull())
    expect(result.current.history).toHaveLength(2)
    expect(result.current.error).toBeNull()
  })

  it('openPath 为空时历史为空且不请求', async () => {
    const { result } = renderHook(() => useFileHistory('p1', null))
    expect(result.current.history).toBeNull()
    expect(mockedList).not.toHaveBeenCalled()
  })

  it('loadPreview 切换预览：再次点击同一快照则收起', async () => {
    mockedList.mockResolvedValue([snapA])
    mockedRead.mockResolvedValue({ ...snapA, content: 'old-code', sha256: 'f'.repeat(64) })
    const { result } = renderHook(() => useFileHistory('p1', 'a.ts'))
    await waitFor(() => expect(result.current.history).not.toBeNull())

    await act(() => result.current.loadPreview(snapA.id))
    expect(result.current.preview).toEqual({ id: snapA.id, content: 'old-code' })

    await act(() => result.current.loadPreview(snapA.id))
    expect(result.current.preview).toBeNull()
  })

  it('restore 成功后刷新历史并返回 true', async () => {
    mockedList.mockResolvedValue([snapA])
    mockedRestore.mockResolvedValue({ path: 'a.ts', size: 10, updatedAt: 't' })
    mockedList.mockResolvedValueOnce([snapA]).mockResolvedValue([snapA, snapB])

    const { result } = renderHook(() => useFileHistory('p1', 'a.ts'))
    await waitFor(() => expect(result.current.history).not.toBeNull())

    let ok = false
    await act(async () => {
      ok = await result.current.restore(snapA.id)
    })
    expect(ok).toBe(true)
    expect(mockedRestore).toHaveBeenCalledWith('p1', snapA.id)
    expect(mockedList).toHaveBeenCalledTimes(2)
  })

  it('restore 失败返回 false 且不抛异常', async () => {
    mockedList.mockResolvedValue([snapA])
    mockedRestore.mockRejectedValue(new Error('boom'))
    const { result } = renderHook(() => useFileHistory('p1', 'a.ts'))
    await waitFor(() => expect(result.current.history).not.toBeNull())

    let ok = true
    await act(async () => {
      ok = await result.current.restore(snapA.id)
    })
    expect(ok).toBe(false)
    expect(result.current.error).toContain('恢复失败')
  })

  it('切换文件后重新加载', async () => {
    mockedList.mockResolvedValue([snapA])
    const { result, rerender } = renderHook(
      ({ path }: { path: string | null }) => useFileHistory('p1', path),
      { initialProps: { path: 'a.ts' } },
    )
    await waitFor(() => expect(result.current.history).not.toBeNull())

    mockedList.mockClear()
    mockedList.mockResolvedValue([])
    rerender({ path: 'b.ts' })
    await waitFor(() => expect(mockedList).toHaveBeenCalledWith('p1', 'b.ts'))
    await waitFor(() => expect(result.current.history).toEqual([]))
  })
})
