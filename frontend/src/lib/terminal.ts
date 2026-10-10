import type { TerminalEntry } from '../types/runner'
import { formatClock } from './labels'

const COLORS: Record<TerminalEntry['kind'], string> = { system: '90', log: '37', info: '96', warn: '93', error: '91' }

/** 输出是用户代码产生的数据，不能允许其控制终端或注入 OSC 链接。 */
export function terminalLine(entry: TerminalEntry): string {
  const text = entry.text.replace(/[\x00-\x08\x0b-\x1f\x7f-\x9f]/g, '').replace(/\r?\n/g, '\r\n')
  return `\x1b[90m${formatClock(entry.at)}\x1b[0m  \x1b[${COLORS[entry.kind]}m${text}\x1b[0m\r\n`
}
