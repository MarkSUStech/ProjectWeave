/**
 * C++ 远程沙箱后端（P4.2c 真实支持：Clang 15 / C++20 / 多翻译单元 /
 * 可选 CMake+Ninja；见 backend sandbox/cpp）。
 *
 * 传输层与 Python 共享（remoteShared）；信任级 practice（D32）。
 */

import { createRemoteBackend } from './remoteShared'

export const remoteCppBackendId = 'remote-cpp'

export const remoteCppBackend = createRemoteBackend({
  backendId: remoteCppBackendId,
  languages: ['cpp'],
})

// 注册
import { registerBackend } from '../registry'
registerBackend(remoteCppBackend)
