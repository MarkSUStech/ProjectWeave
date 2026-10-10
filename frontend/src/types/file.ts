/**
 * 项目文件（工作区）的前端类型契约，镜像
 * backend/app/domains/projects/file_schemas.py。
 */
import { z } from 'zod'

export const fileMetaSchema = z.object({
  path: z.string(),
  size: z.number().int().nonnegative(),
  updatedAt: z.string(),
})

export const fileListSchema = z.object({
  items: z.array(fileMetaSchema),
  total: z.number().int().nonnegative(),
})

export const fileReadSchema = z.object({
  path: z.string(),
  content: z.string(),
  updatedAt: z.string(),
})

export type FileMeta = z.infer<typeof fileMetaSchema>
export type FileRead = z.infer<typeof fileReadSchema>

/** 快照历史（与 file_schemas.py 的 Snapshot* 镜像）。 */
export const snapshotMetaSchema = z.object({
  id: z.string().uuid(),
  path: z.string(),
  size: z.number().int().nonnegative(),
  sha256: z.string(),
  createdAt: z.string(),
})

export const snapshotListSchema = z.object({
  items: z.array(snapshotMetaSchema),
  total: z.number().int().nonnegative(),
})

export const snapshotReadSchema = z.object({
  id: z.string().uuid(),
  path: z.string(),
  content: z.string(),
  sha256: z.string(),
  createdAt: z.string(),
})

export const codeVersionSchema = z.object({
  codeVersion: z.string(),
  fileCount: z.number().int().nonnegative(),
})

export type SnapshotMeta = z.infer<typeof snapshotMetaSchema>
export type SnapshotRead = z.infer<typeof snapshotReadSchema>
export type CodeVersionInfo = z.infer<typeof codeVersionSchema>
