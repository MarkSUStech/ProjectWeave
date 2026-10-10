/**
 * Monaco 本地打包配置（不依赖 CDN）。
 *
 * monaco-editor 0.5x 在打包器环境下通过 `new Worker(new URL(...))`
 * 自行创建语言/基础 worker（含 esmModuleLocationBundler 描述符），
 * Vite 会原生处理这些 URL 引用，因此无需手动 `?worker` 导入——
 * 该包的 exports 映射也无法通过深层路径静态导入 worker。
 */
import { loader } from '@monaco-editor/react'
import * as monaco from 'monaco-editor'

let configured = false

export function configureMonaco(): typeof monaco {
  if (configured) return monaco
  configured = true
  // 让 @monaco-editor/react 使用本地打包的 monaco 实例而非 CDN。
  loader.config({ monaco })
  return monaco
}
