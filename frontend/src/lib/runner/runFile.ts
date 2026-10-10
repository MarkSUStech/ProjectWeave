/**
 * 按文件类型分发执行：
 * - .js/.mjs/.cjs 直接执行；
 * - .ts/.mts/.cts 用真实 TypeScript 编译器（ts-compiler 别名，npm:typescript@5）
 *   单文件转译后执行——转译不等于类型检查，界面上明确标注；
 * - 其他类型明确拒绝，不静默假装成功。
 */

const DIRECT_EXTENSIONS = new Set(['js', 'mjs', 'cjs'])
const TYPESCRIPT_EXTENSIONS = new Set(['ts', 'mts', 'cts'])

export function extensionOf(path: string): string {
  const name = path.split('/').pop() ?? ''
  const dot = name.lastIndexOf('.')
  return dot === -1 ? '' : name.slice(dot + 1).toLowerCase()
}

/** 测试文件约定：`*.test.<js|ts 系>`（如 src/main.test.ts）。 */
export function isTestPath(path: string): boolean {
  const name = path.split('/').pop() ?? ''
  const match = name.match(/\.test\.([cm]?[jt]s)$/)
  return match !== null && isRunnablePath(path)
}

export function isRunnablePath(path: string): boolean {
  const extension = extensionOf(path)
  return DIRECT_EXTENSIONS.has(extension) || TYPESCRIPT_EXTENSIONS.has(extension)
}

export interface PreparedScript {
  status: 'ok' | 'unsupported'
  code: string
  transpiled: boolean
  reason?: string
}

export async function prepareScript(path: string, content: string): Promise<PreparedScript> {
  const extension = extensionOf(path)
  if (DIRECT_EXTENSIONS.has(extension)) {
    return { status: 'ok', code: content, transpiled: false }
  }
  if (TYPESCRIPT_EXTENSIONS.has(extension)) {
    const ts = await import('ts-compiler')
    const output = ts.transpileModule(content, {
      compilerOptions: {
        target: ts.ScriptTarget.ES2020,
        module: ts.ModuleKind.None,
      },
    })
    return { status: 'ok', code: output.outputText, transpiled: true }
  }
  return {
    status: 'unsupported',
    code: '',
    transpiled: false,
    reason: `浏览器运行器当前支持 .js/.ts 文件，不支持 .${extension || '（无扩展名）'} 文件`,
  }
}
