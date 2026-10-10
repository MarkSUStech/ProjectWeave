/**
 * 项目文件的工作台状态 hook：文件树、当前打开文件、脏状态与保存。
 *
 * 未保存内容只存在于内存（draftContent）；保存通过 PUT 持久化到
 * 服务器。切换文件时若有未保存修改会请求用户确认。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  deleteFile as apiDeleteFile,
  listFiles,
  readFile as apiReadFile,
  renameFile as apiRenameFile,
  writeFile,
} from '../api/files'
import { ApiError } from '../api/client'
import type { FileMeta } from '../types/file'

/** 自动保存防抖间隔；传 null 关闭。 */
export const DEFAULT_AUTOSAVE_MS = 2500

export interface UseProjectFilesResult {
  /** null 表示尚未加载完成。 */
  files: FileMeta[] | null
  treeError: string | null
  openPath: string | null
  /** 服务器上已保存的内容。 */
  savedContent: string
  /** 当前编辑中的内容（可能包含未保存修改）。 */
  draftContent: string
  dirty: boolean
  /** 打开/保存等单文件操作的错误信息。 */
  fileError: string | null
  saving: boolean
  openFile: (path: string) => Promise<void>
  setDraft: (content: string) => void
  save: () => Promise<void>
  createFile: (path: string) => Promise<boolean>
  renameFile: (path: string, newPath: string) => Promise<boolean>
  deleteFile: (path: string) => Promise<boolean>
  /** 从服务器重读当前打开文件（恢复快照等场景，草稿被覆盖）。 */
  reloadCurrent: () => Promise<void>
  refresh: () => Promise<void>
}

function messageOf(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback
}

export interface UseProjectFilesOptions {
  /** 自动保存防抖间隔（毫秒）；null 关闭。默认 2500。 */
  autoSaveMs?: number | null
}

export function useProjectFiles(
  projectId: string,
  options: UseProjectFilesOptions = {},
): UseProjectFilesResult {
  const { autoSaveMs = DEFAULT_AUTOSAVE_MS } = options
  const [files, setFiles] = useState<FileMeta[] | null>(null)
  const [treeError, setTreeError] = useState<string | null>(null)
  const [openPath, setOpenPath] = useState<string | null>(null)
  const [savedContent, setSavedContent] = useState('')
  const [draftContent, setDraftContent] = useState('')
  const [fileError, setFileError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  /** 记录打开动作的代次，避免慢请求覆盖较新的打开结果。 */
  const openEpoch = useRef(0)

  const refresh = useCallback(async () => {
    setTreeError(null)
    try {
      setFiles(await listFiles(projectId))
    } catch (err) {
      setFiles([])
      setTreeError(messageOf(err, '文件列表加载失败'))
    }
  }, [projectId])

  useEffect(() => {
    let cancelled = false
    openEpoch.current += 1
    setFiles(null)
    setTreeError(null)
    setOpenPath(null)
    setSavedContent('')
    setDraftContent('')

    void (async () => {
      try {
        const items = await listFiles(projectId)
        if (cancelled) return
        setFiles(items)
        // 默认打开 README.md，否则第一个文件，提升首次进入体验。
        const preferred =
          items.find((f) => f.path === 'README.md') ?? (items.length > 0 ? items[0] : undefined)
        if (preferred) {
          const epoch = ++openEpoch.current
          const detail = await apiReadFile(projectId, preferred.path)
          if (cancelled || epoch !== openEpoch.current) return
          setOpenPath(detail.path)
          setSavedContent(detail.content)
          setDraftContent(detail.content)
        }
      } catch (err) {
        if (!cancelled) {
          setFiles([])
          setTreeError(messageOf(err, '文件加载失败'))
        }
      }
    })()

    return () => {
      cancelled = true
    }
  }, [projectId])

  const openFile = useCallback(
    async (path: string) => {
      if (path === openPath) return
      if (draftContent !== savedContent) {
        const proceed = window.confirm(`「${openPath ?? '当前文件'}」有未保存的修改，切换后将丢失。是否继续？`)
        if (!proceed) return
      }
      setFileError(null)
      const epoch = ++openEpoch.current
      try {
        const detail = await apiReadFile(projectId, path)
        if (epoch !== openEpoch.current) return
        setOpenPath(detail.path)
        setSavedContent(detail.content)
        setDraftContent(detail.content)
      } catch (err) {
        setFileError(messageOf(err, '文件打开失败'))
      }
    },
    [projectId, openPath, draftContent, savedContent],
  )

  const setDraft = useCallback((content: string) => {
    setDraftContent(content)
  }, [])

  const save = useCallback(async () => {
    if (!openPath || saving || draftContent === savedContent) return
    setSaving(true)
    setFileError(null)
    try {
      const meta = await writeFile(projectId, openPath, draftContent)
      setSavedContent(draftContent)
      setFiles((current) =>
        current === null
          ? current
          : current.map((f) => (f.path === meta.path ? meta : f)),
      )
    } catch (err) {
      setFileError(messageOf(err, '保存失败'))
    } finally {
      setSaving(false)
    }
  }, [projectId, openPath, saving, draftContent, savedContent])

  const createFile = useCallback(    async (path: string) => {
      setFileError(null)
      try {
        await writeFile(projectId, path, '')
        await refresh()
        const detail = await apiReadFile(projectId, path)
        const epoch = ++openEpoch.current
        if (epoch !== openEpoch.current) return false
        setOpenPath(detail.path)
        setSavedContent(detail.content)
        setDraftContent(detail.content)
        return true
      } catch (err) {
        setFileError(messageOf(err, '创建文件失败'))
        return false
      }
    },
    [projectId, refresh],
  )

  const renameFile = useCallback(
    async (path: string, newPath: string) => {
      setFileError(null)
      try {
        await apiRenameFile(projectId, path, newPath)
        if (openPath === path) setOpenPath(newPath)
        await refresh()
        return true
      } catch (err) {
        setFileError(messageOf(err, '重命名失败'))
        return false
      }
    },
    [projectId, openPath, refresh],
  )

  const deleteFile = useCallback(
    async (path: string) => {
      setFileError(null)
      try {
        await apiDeleteFile(projectId, path)
        if (openPath === path) {
          openEpoch.current += 1
          setOpenPath(null)
          setSavedContent('')
          setDraftContent('')
        }
        await refresh()
        return true
      } catch (err) {
        setFileError(messageOf(err, '删除失败'))
        return false
      }
    },
    [projectId, openPath, refresh],
  )

  const dirty = draftContent !== savedContent

  const reloadCurrent = useCallback(async () => {    if (!openPath) return
    setFileError(null)
    const epoch = ++openEpoch.current
    try {
      const detail = await apiReadFile(projectId, openPath)
      if (epoch !== openEpoch.current) return
      setOpenPath(detail.path)
      setSavedContent(detail.content)
      setDraftContent(detail.content)
    } catch (err) {
      setFileError(messageOf(err, '文件刷新失败'))
    }
  }, [projectId, openPath])

  // 防抖自动保存：有未保存修改且停止输入 autoSaveMs 后触发。
  // 每次输入都会重置计时器；手动保存/失败后 dirty 状态继续驱动下一轮。
  useEffect(() => {
    if (autoSaveMs === null || openPath === null || !dirty || saving) return
    const timer = setTimeout(() => {
      void save()
    }, autoSaveMs)
    return () => clearTimeout(timer)
  }, [autoSaveMs, openPath, dirty, saving, draftContent, save])

  return {
    files,
    treeError,
    openPath,
    savedContent,
    draftContent,
    dirty,
    fileError,
    saving,
    openFile,
    setDraft,
    save,
    createFile,
    renameFile,
    deleteFile,
    reloadCurrent,
    refresh,
  }
}
