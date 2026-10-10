/**
 * 按文件类型分发执行：
 * - .js/.mjs/.cjs 直接执行；
 * - .ts/.mts/.cts 单文件无 import → ts-compiler 转译执行；
 * - 有相对 import/export → esbuild-wasm 多文件打包后执行（P4.2a）；
 * - 其他类型明确拒绝。
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
  status: 'ok' | 'unsupported' | 'error'
  code: string
  transpiled: boolean
  reason?: string
  /** 打包耗时（毫秒），多文件模式。 */
  buildTimeMs?: number
  /** 参与构建的模块列表，多文件模式。 */
  modules?: string[]
}

/** 单文件转译（无相对 import 的 .ts）。 */
async function transpileSingle(content: string): Promise<PreparedScript> {
  const ts = await import('ts-compiler')
  const output = ts.transpileModule(content, {
    compilerOptions: {
      target: ts.ScriptTarget.ES2020,
      module: ts.ModuleKind.CommonJS,
    },
  })
  const code = `await (async (exports) => {\n${output.outputText}\n})(Object.create(null));`
  return { status: 'ok', code, transpiled: true }
}

/** 多文件打包（有相对 import/export）。 */
async function bundleMulti(
  path: string,
  content: string,
  vfs?: Map<string, string>,
): Promise<PreparedScript> {
  if (!vfs) {
    return {
      status: 'error', code: '', transpiled: false,
      reason: '检测到 import/export 但未提供项目文件系统——无法解析模块依赖',
    }
  }
  // 入口文件用传入内容（可能是编辑器草稿），其余从 VFS 读
  const fs = new Map(vfs)
  fs.set(path, content)
  const { bundleModule, hasRelativeImports } = await import('./bundler')
  if (!hasRelativeImports(content)) {
    // 只有 export 没有 import → 也不需要打包
    return transpileSingle(content)
  }
  const result = await bundleModule(path, fs)
  if (result.status === 'error') {
    return {
      status: 'error', code: '', transpiled: false,
      reason: result.error, buildTimeMs: result.buildTimeMs, modules: result.modules,
    }
  }
  return {
    status: 'ok', code: result.code, transpiled: true,
    buildTimeMs: result.buildTimeMs, modules: result.modules,
  }
}

export async function prepareScript(
  path: string,
  content: string,
  vfs?: Map<string, string>,
): Promise<PreparedScript> {
  const extension = extensionOf(path)
  // 无 VFS = 单文件模式：export 语句可转译执行，不触发打包路径。
  if (!vfs) {
    if (DIRECT_EXTENSIONS.has(extension)) {
      return { status: 'ok', code: content, transpiled: false }
    }
    if (TYPESCRIPT_EXTENSIONS.has(extension)) {
      return transpileSingle(content)
    }
  }
  if (DIRECT_EXTENSIONS.has(extension)) {
    const { hasRelativeImports } = await import('./bundler')
    if (hasRelativeImports(content) && vfs) {
      return bundleMulti(path, content, vfs)
    }
    return { status: 'ok', code: content, transpiled: false }
  }
  if (TYPESCRIPT_EXTENSIONS.has(extension)) {
    const { hasRelativeImports } = await import('./bundler')
    if (hasRelativeImports(content) || /(?:^|\n)\s*import\s+/.test(content)) {
      return bundleMulti(path, content, vfs)
    }
    return transpileSingle(content)
  }
  return {
    status: 'unsupported',
    code: '',
    transpiled: false,
    reason: `浏览器运行器当前支持 .js/.ts 文件，不支持 .${extension || '（无扩展名）'} 文件`,
  }
}
