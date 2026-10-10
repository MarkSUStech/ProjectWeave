/**
 * Python 远程沙箱后端（P4.2b 起真实支持；P4.2c 起传输层抽至 remoteShared）。
 *
 * 信任级：practice（服务端执行 ≠ 正式认证，见 D32）。
 */

import { createRemoteBackend } from './remoteShared'

export const remotePythonBackendId = 'remote-pytest'

// 共享传输层的再导出（runRemote.ts 与既有测试依赖这些名字）
export {
  executeRemoteWithStream,
  getActiveRemoteExecutionId,
  cancelActiveRemoteExecution,
  remoteExecutionErrorMessage,
} from './remoteShared'
export type { RemoteExecutionExtras } from './remoteShared'

export const remotePythonBackend = createRemoteBackend({
  backendId: remotePythonBackendId,
  languages: ['python'],
})

// 注册
import { registerBackend } from '../registry'
registerBackend(remotePythonBackend)
