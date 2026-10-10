/**
 * 远程沙箱后端（占位接口，P4.2a 不实现）。
 *
 * 设计预留：
 * - Python：CPython + pytest + debugpy（remote-pytest 后端）
 * - C++：Clang/GCC + CMake + LLDB（remote-cmake 后端）
 * - 信任级：formal（服务端可信执行，可用于正式验收）
 *
 * 实现时只需：
 * 1. 实现此接口
 * 2. 在对应 LanguageProfile 的 supportedBackends 中注册 backendId
 * 3. 不需要修改 Curriculum/Learner/TeachingScene
 */

import type { ExecutionRequest, ExecutionResult, BackendCapabilities } from '../types'
import type { ExecutionBackend } from '../ExecutionBackend'
import type { LanguageProfile } from '../LanguageProfile'

export const REMOTE_BACKEND_STUB_NOTE = '远程沙箱后端尚未实现——不伪造运行能力（P4.2a 仅定义接口）'

export function createRemoteBackendStub(
  backendId: string,
  languages: string[],
): ExecutionBackend {
  return {
    backendId,
    capabilities: {
      languages,
      multiFile: true,
      testRunner: true,
      inBrowser: false,
      maxTrustLevel: 'formal',
    } satisfies BackendCapabilities,
    canHandle(_request: ExecutionRequest, _profile: LanguageProfile): boolean {
      return false // 未实现 → 始终返回 false，registry 不会选中
    },
    async execute(_request: ExecutionRequest): Promise<ExecutionResult> {
      throw new Error(REMOTE_BACKEND_STUB_NOTE)
    },
  }
}

// 预留后端 ID（仅定义，不注册到 registry——canHandle=false 无意义）
export const REMOTE_BACKEND_IDS = {
  pythonPytest: 'remote-pytest',
  cppCmake: 'remote-cmake',
  generic: 'remote-sandbox',
} as const
