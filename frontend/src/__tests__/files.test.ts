/** 文件契约与文件 API 客户端测试。 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  fileListSchema,
  fileMetaSchema,
  fileReadSchema,
} from '../types/file'
import { deleteFile, listFiles, readFile, renameFile, writeFile } from '../api/files'

const meta = { path: 'src/main.ts', size: 128, updatedAt: '2026-10-10T04:00:00Z' }

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

describe('文件契约 schema', () => {
  it('解析合法 meta / list / read', () => {
    expect(fileMetaSchema.parse(meta)).toEqual(meta)
    const list = fileListSchema.parse({ items: [meta], total: 1 })
    expect(list.total).toBe(1)
    const read = fileReadSchema.parse({
      path: 'README.md',
      content: '# hi',
      updatedAt: '2026-10-10T04:00:00Z',
    })
    expect(read.content).toBe('# hi')
  })

  it('拒绝负数 size / 非整数 total', () => {
    expect(() => fileMetaSchema.parse({ ...meta, size: -1 })).toThrow()
    expect(() => fileListSchema.parse({ items: [], total: 1.5 })).toThrow()
  })
})

describe('文件 API 客户端', () => {
  it('listFiles 指向项目 files 路径', async () => {
    const fetchMock = mockFetch(200, { items: [meta], total: 1 })
    vi.stubGlobal('fetch', fetchMock)
    const items = await listFiles('p1')
    expect(items).toHaveLength(1)
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/projects/p1/files', expect.anything())
  })

  it('readFile 对路径做 URL 编码', async () => {
    const fetchMock = mockFetch(200, { path: 'a b.ts', content: 'x', updatedAt: 't' })
    vi.stubGlobal('fetch', fetchMock)
    await readFile('p1', 'a b.ts')
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/v1/projects/p1/files/content?path=a%20b.ts')
  })

  it('writeFile 使用 PUT 且请求体为 camelCase', async () => {
    const fetchMock = mockFetch(201, meta)
    vi.stubGlobal('fetch', fetchMock)
    await writeFile('p1', 'src/main.ts', 'const a = 1;')
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/v1/projects/p1/files')
    expect(init.method).toBe('PUT')
    expect(JSON.parse(init.body as string)).toEqual({
      path: 'src/main.ts',
      content: 'const a = 1;',
    })
  })

  it('renameFile 使用 PATCH 且携带 newPath', async () => {
    const fetchMock = mockFetch(200, meta)
    vi.stubGlobal('fetch', fetchMock)
    await renameFile('p1', 'a.md', 'b.md')
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(init.method).toBe('PATCH')
    expect(JSON.parse(init.body as string)).toEqual({ path: 'a.md', newPath: 'b.md' })
  })

  it('deleteFile 使用 DELETE 且路径编码在查询参数', async () => {
    const fetchMock = mockFetch(204, undefined)
    vi.stubGlobal('fetch', fetchMock)
    await deleteFile('p1', 'a b.ts')
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/v1/projects/p1/files?path=a%20b.ts')
    expect(init.method).toBe('DELETE')
  })

  it('fileReadSchema 校验失败的响应抛出 ZodError', async () => {
    vi.stubGlobal('fetch', mockFetch(200, { path: 'x' })) // 缺 content/updatedAt
    await expect(readFile('p1', 'x')).rejects.toThrow()
  })
})
