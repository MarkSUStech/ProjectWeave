/**
 * 多文件模块打包器（P4.2a）：esbuild-wasm + 虚拟文件系统插件。
 *
 * 将项目内部 JS/TS 模块的相对 import/export 打包为单个可执行脚本，
 * 送入现有 Worker 沙箱运行。esbuild-wasm 懒加载（首次多文件运行才
 * 下载 ~14MB WASM），初始化后复用。
 *
 * 安全约束：
 * - 路径规范化，禁止 .. 越界与绝对路径；
 * - 只解析 VFS 中存在的文件，外部 npm 包返回明确错误；
 * - 编译异常报告具体文件与行号，不伪装为运行成功。
 */

import type * as Esbuild from 'esbuild-wasm'

/** 虚拟文件系统：项目路径 → 文件内容。 */
export type VirtualFS = Map<string, string>

export interface BundleResult {
  status: 'ok' | 'error'
  code: string
  /** 打包耗时（毫秒），用于性能观测。 */
  buildTimeMs: number
  error?: string
  /** 参与构建的文件路径列表（含入口）。 */
  modules: string[]
}

// ---- 路径解析（安全，无 fs 访问） ----

const SOURCE_EXTENSIONS = ['.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.mts', '.cts']

function normalizePath(path: string): string {
  const parts = path.split('/')
  const resolved: string[] = []
  for (const part of parts) {
    if (part === '' || part === '.') continue
    if (part === '..') {
      if (resolved.length === 0) return '' // 越界
      resolved.pop()
      continue
    }
    resolved.push(part)
  }
  return resolved.join('/')
}

/** 解析相对导入到 VFS 中的实际路径（尝试扩展名补全）。 */
export function resolveImport(
  importer: string,
  specifier: string,
  fs: VirtualFS,
): { path: string } | { error: string } {
  if (!specifier.startsWith('./') && !specifier.startsWith('../')) {
    return { error: `不支持外部包导入 "${specifier}"（当前仅支持项目内相对导入）` }
  }
  const baseDir = importer.includes('/') ? importer.slice(0, importer.lastIndexOf('/')) : ''
  const joined = baseDir ? `${baseDir}/${specifier}` : specifier
  const normalized = normalizePath(joined)
  if (!normalized) {
    return { error: `路径越界：${importer} → ${specifier}` }
  }
  // 1. 精确匹配
  if (fs.has(normalized)) return { path: normalized }
  // 2. 尝试补全扩展名
  for (const ext of SOURCE_EXTENSIONS) {
    const withExt = normalized + ext
    if (fs.has(withExt)) return { path: withExt }
  }
  // 3. 尝试 /index
  for (const ext of SOURCE_EXTENSIONS) {
    const index = `${normalized}/index${ext}`
    if (fs.has(index)) return { path: index }
  }
  return { error: `模块不存在：${specifier}（从 ${importer} 导入；已尝试 ${SOURCE_EXTENSIONS.slice(0, 4).join('/')} 等扩展名）` }
}

function loaderFor(path: string): Esbuild.Loader {
  if (path.endsWith('.ts') || path.endsWith('.mts') || path.endsWith('.cts')) return 'ts'
  if (path.endsWith('.tsx')) return 'tsx'
  if (path.endsWith('.jsx')) return 'jsx'
  return 'js'
}

// ---- esbuild-wasm 懒初始化（单例） ----

let esbuildModule: typeof Esbuild | null = null
let initPromise: Promise<typeof Esbuild> | null = null

async function getEsbuild(): Promise<typeof Esbuild> {
  if (esbuildModule) return esbuildModule
  if (initPromise) return initPromise
  initPromise = (async () => {
    const mod = await import('esbuild-wasm')
    await mod.initialize({
      wasmURL: new URL('/esbuild.wasm', globalThis.location?.origin ?? 'http://localhost:5173').href,
      worker: true,
    })
    esbuildModule = mod
    return mod
  })()
  return initPromise
}

// ---- 打包 ----

export async function bundleModule(
  entryPath: string,
  fs: VirtualFS,
): Promise<BundleResult> {
  const startedAt = performance.now()
  if (!fs.has(entryPath)) {
    return {
      status: 'error', code: '', buildTimeMs: 0,
      error: `入口文件不存在：${entryPath}`, modules: [],
    }
  }

  let esbuild: typeof Esbuild
  try {
    esbuild = await getEsbuild()
  } catch (err) {
    return {
      status: 'error', code: '', buildTimeMs: performance.now() - startedAt,
      error: `编译器加载失败：${err instanceof Error ? err.message : String(err)}`, modules: [],
    }
  }

  const builtModules: string[] = []

  const vfsPlugin: Esbuild.Plugin = {
    name: 'virtual-fs',
    setup(build) {
      build.onResolve({ filter: /^\.\/|^\.\.\// }, (args) => {
        const result = resolveImport(args.importer, args.path, fs)
        if ('error' in result) {
          return {
            errors: [{ text: result.error, location: { file: args.importer, namespace: 'vfs' } }],
          }
        }
        return { path: result.path, namespace: 'vfs' }
      })
      // 外部包（不以 ./ 或 ../ 开头）→ 明确错误
      build.onResolve({ filter: /.*/ }, (args) => {
        if (args.namespace === 'vfs') return undefined // 让上面的 handler 处理
        return {
          errors: [{
            text: `不支持外部包 "${args.path}"（仅支持项目内相对导入 ./ 或 ../）`,
            location: args.importer ? { file: args.importer, namespace: 'vfs' } : undefined,
          }],
        }
      })
      build.onLoad({ filter: /.*/, namespace: 'vfs' }, (args) => {
        const content = fs.get(args.path)
        if (content === undefined) {
          return { errors: [{ text: `文件不存在：${args.path}` }] }
        }
        builtModules.push(args.path)
        return { contents: content, loader: loaderFor(args.path) }
      })
    },
  }

  try {
    const result = await esbuild.build({
      entryPoints: [entryPath],
      bundle: true,
      format: 'iife',
      target: 'es2020',
      write: false,
      plugins: [vfsPlugin],
      sourcemap: 'inline',
      logLevel: 'silent',
    })
    const code = result.outputFiles?.[0]?.text ?? ''
    if (!code) {
      return {
        status: 'error', code: '', buildTimeMs: performance.now() - startedAt,
        error: '打包结果为空', modules: builtModules,
      }
    }
    return {
      status: 'ok', code,
      buildTimeMs: Math.round(performance.now() - startedAt),
      modules: builtModules,
    }
  } catch (err) {
    const esbuildErr = err as { errors?: Array<{ text?: string; location?: { file?: string; line?: number } }> }
    const messages = (esbuildErr.errors ?? []).map((e) => {
      const loc = e.location?.file ? `（${e.location.file}${e.location.line ? `:${e.location.line}` : ''}）` : ''
      return `${e.text ?? '编译错误'}${loc}`
    })
    return {
      status: 'error', code: '', buildTimeMs: performance.now() - startedAt,
      error: messages.length > 0 ? messages.join('；') : `打包失败：${err instanceof Error ? err.message : String(err)}`,
      modules: builtModules,
    }
  }
}

/** 判断文件是否包含相对 import/export（决定是否需要打包模式）。 */
export function hasRelativeImports(content: string): boolean {
  return /(?:^|\n)\s*(?:import\s.+?\sfrom\s+|export\s.+?\sfrom\s+|import\s+')['"]\.\.?\/.+?['"]/.test(content)
    || /(?:^|\n)\s*export\s+(?:function|const|let|var|class|interface|type|enum)\s/.test(content)
}
