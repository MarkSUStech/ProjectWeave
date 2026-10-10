/**
 * 当前打开文件的快照历史：列表、内容预览与恢复。
 * openPath 或已保存版本变化时自动重新加载。
 */
import { useCallback, useEffect, useState } from 'react'
import {
  listFileHistory,
  readSnapshot,
  restoreSnapshot,
} from '../api/files'
import type { SnapshotMeta } from '../types/file'

export interface UseFileHistoryResult {
  history: SnapshotMeta[] | null
  error: string | null
  /** 当前展开预览的快照内容。 */
  preview: { id: string; content: string } | null
  previewLoading: boolean
  restoring: boolean
  loadPreview: (snapshotId: string) => Promise<void>
  /** 恢复成功返回 true；调用方负责刷新编辑器与文件树。 */
  restore: (snapshotId: string) => Promise<boolean>
  refresh: () => Promise<void>
}

export function useFileHistory(projectId: string, openPath: string | null, savedAt?: string): UseFileHistoryResult {
  const [history, setHistory] = useState<SnapshotMeta[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [preview, setPreview] = useState<{ id: string; content: string } | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [restoring, setRestoring] = useState(false)

  const refresh = useCallback(async () => {
    if (openPath === null) {
      setHistory(null)
      return
    }
    setError(null)
    try {
      setHistory(await listFileHistory(projectId, openPath))
    } catch {
      setHistory([])
      setError('快照历史加载失败')
    }
  }, [projectId, openPath])

  useEffect(() => {
    setPreview(null)
    setError(null)
    if (openPath === null) {
      setHistory(null)
      return
    }
    setHistory(null)
    void refresh()
  }, [openPath, refresh, savedAt])

  const loadPreview = useCallback(
    async (snapshotId: string) => {
      if (preview?.id === snapshotId) {
        setPreview(null)
        return
      }
      setPreviewLoading(true)
      try {
        const snapshot = await readSnapshot(projectId, snapshotId)
        setPreview({ id: snapshotId, content: snapshot.content })
      } catch {
        setError('快照读取失败')
      } finally {
        setPreviewLoading(false)
      }
    },
    [projectId, preview],
  )

  const restore = useCallback(
    async (snapshotId: string) => {
      setRestoring(true)
      setError(null)
      try {
        await restoreSnapshot(projectId, snapshotId)
        await refresh()
        return true
      } catch {
        setError('恢复失败，请重试')
        return false
      } finally {
        setRestoring(false)
      }
    },
    [projectId, refresh],
  )

  return { history, error, preview, previewLoading, restoring, loadPreview, restore, refresh }
}
