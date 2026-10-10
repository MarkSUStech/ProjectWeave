/** 快照/版本 API 客户端与契约测试。 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  codeVersionSchema,
  snapshotListSchema,
  snapshotMetaSchema,
} from '../types/file'
import {
  getCodeVersion,
  listFileHistory,
  readSnapshot,
  restoreSnapshot,
} from '../api/files'

function mockFetch(status: number, body: unknown) {
  return vi.fn().mockResolvedValue(
    new Response(body === undefined ? null : JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

const snapshot = {
  id: '0e0f26b4-7e4d-4c8f-9d3a-2f4f5c6a7b8d',
  path: 'src/main.ts',
  size: 128,
  sha256: 'abc123def456',
  createdAt: '2026-10-10T05:00:00Z',
}

describe('快照契约 schema', () => {
  it('解析合法 meta / list / codeVersion', () => {
    expect(snapshotMetaSchema.parse(snapshot)).toEqual(snapshot)
    expect(snapshotListSchema.parse({ items: [snapshot], total: 1 }).total).toBe(1)
    expect(codeVersionSchema.parse({ codeVersion: 'sha256:abc', fileCount: 3 })).toEqual({
      codeVersion: 'sha256:abc',
      fileCount: 3,
    })
  })

  it('拒绝负数 size / 非 UUID id', () => {
    expect(() => snapshotMetaSchema.parse({ ...snapshot, size: -1 })).toThrow()
    expect(() => snapshotMetaSchema.parse({ ...snapshot, id: 'nope' })).toThrow()
  })
})

describe('快照 API 客户端', () => {
  it('listFileHistory 查询参数编码路径', async () => {
    const fetchMock = mockFetch(200, { items: [snapshot], total: 1 })
    vi.stubGlobal('fetch', fetchMock)
    await listFileHistory('p1', 'src/a b.ts')
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/v1/projects/p1/files/history?path=src%2Fa%20b.ts')
  })

  it('readSnapshot 指向快照详情', async () => {
    const fetchMock = mockFetch(200, { ...snapshot, content: 'x', sha256: 'f'.repeat(64) })
    vi.stubGlobal('fetch', fetchMock)
    await readSnapshot('p1', snapshot.id)
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/projects/p1/files/history/${snapshot.id}`,
      expect.anything(),
    )
  })

  it('restoreSnapshot 使用 POST 并解析文件元数据', async () => {
    const fetchMock = mockFetch(200, { path: 'src/main.ts', size: 3, updatedAt: 't' })
    vi.stubGlobal('fetch', fetchMock)
    await restoreSnapshot('p1', snapshot.id)
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe(`/api/v1/projects/p1/files/history/${snapshot.id}/restore`)
    expect(init.method).toBe('POST')
  })

  it('getCodeVersion 指向项目版本端点', async () => {
    const fetchMock = mockFetch(200, { codeVersion: 'sha256:abc', fileCount: 2 })
    vi.stubGlobal('fetch', fetchMock)
    const info = await getCodeVersion('p1')
    expect(info.codeVersion).toBe('sha256:abc')
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/projects/p1/code-version', expect.anything())
  })
})
