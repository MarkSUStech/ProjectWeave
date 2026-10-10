/** 项目文件资源 API：响应经 zod 校验。 */

import { api } from './client'
import {
  codeVersionSchema,
  fileListSchema,
  fileMetaSchema,
  fileReadSchema,
  snapshotListSchema,
  snapshotReadSchema,
  type CodeVersionInfo,
  type FileMeta,
  type FileRead,
  type SnapshotMeta,
  type SnapshotRead,
} from '../types/file'

function base(projectId: string): string {
  return `/projects/${projectId}/files`
}

export async function listFiles(projectId: string): Promise<FileMeta[]> {
  const data = await api.get<unknown>(base(projectId))
  return fileListSchema.parse(data).items
}

export async function readFile(projectId: string, path: string): Promise<FileRead> {
  const data = await api.get<unknown>(
    `${base(projectId)}/content?path=${encodeURIComponent(path)}`,
  )
  return fileReadSchema.parse(data)
}

/** 创建或整体替换文件。 */
export async function writeFile(
  projectId: string,
  path: string,
  content: string,
): Promise<FileMeta> {
  const data = await api.put<unknown>(base(projectId), { path, content })
  return fileMetaSchema.parse(data)
}

export async function renameFile(
  projectId: string,
  path: string,
  newPath: string,
): Promise<FileMeta> {
  const data = await api.patch<unknown>(base(projectId), { path, newPath })
  return fileMetaSchema.parse(data)
}

export async function deleteFile(projectId: string, path: string): Promise<void> {
  await api.delete<unknown>(`${base(projectId)}?path=${encodeURIComponent(path)}`)
}

/** 项目当前代码状态指纹（内容变则变）。 */
export async function getCodeVersion(projectId: string): Promise<CodeVersionInfo> {
  const data = await api.get<unknown>(`/projects/${projectId}/code-version`)
  return codeVersionSchema.parse(data)
}

export async function listFileHistory(projectId: string, path: string): Promise<SnapshotMeta[]> {
  const data = await api.get<unknown>(
    `${base(projectId)}/history?path=${encodeURIComponent(path)}`,
  )
  return snapshotListSchema.parse(data).items
}

export async function readSnapshot(projectId: string, snapshotId: string): Promise<SnapshotRead> {
  const data = await api.get<unknown>(`${base(projectId)}/history/${snapshotId}`)
  return snapshotReadSchema.parse(data)
}

/** 恢复快照（当前内容会先进入历史，不丢数据）。 */
export async function restoreSnapshot(
  projectId: string,
  snapshotId: string,
): Promise<FileMeta> {
  const data = await api.post<unknown>(`${base(projectId)}/history/${snapshotId}/restore`)
  return fileMetaSchema.parse(data)
}
