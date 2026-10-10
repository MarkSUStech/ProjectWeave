/**
 * 执行内容指纹（设计 §14.3 codeVersion 的运行侧形态）。
 *
 * 服务器 codeVersion 描述"已保存状态"；浏览器运行执行的是编辑器草稿，
 * 因此运行数据的绑定指纹 = SHA-256(`${path}\0${content}`)（多文件用 \n 连接）。
 * 同内容必然同指纹；内容变化指纹即变——画布据此判定"数据已过期"。
 *
 * 测试等无 crypto.subtle 环境降级为确定性 FNV-1a（两种实现不混用：
 * 同一环境内指纹自洽；生产浏览器始终走 SHA-256）。
 */

export async function fingerprint(...parts: string[]): Promise<string> {
  const input = parts.join('\x00')
  const subtle = globalThis.crypto?.subtle
  if (subtle) {
    const digest = await subtle.digest('SHA-256', new TextEncoder().encode(input))
    return 'sha256:' + [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('')
  }
  return 'fnv1a:' + fnv1aHex(input)
}

function fnv1aHex(input: string): string {
  // 64 位 FNV-1a（BigInt），仅测试环境使用
  let hash = 0xcbf29ce484222325n
  for (let i = 0; i < input.length; i += 1) {
    hash ^= BigInt(input.charCodeAt(i))
    hash = (hash * 0x100000001b3n) & 0xffffffffffffffffn
  }
  return hash.toString(16).padStart(16, '0')
}

/** 展示用缩写（如 sha256:a1b2c3… → sha256:a1b2c3）。 */
export function shortFingerprint(value: string, keep = 12): string {
  const colon = value.indexOf(':')
  return colon === -1 ? value.slice(0, keep) : value.slice(0, colon + 1 + keep)
}
