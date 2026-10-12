/**
 * CMake 项目控件（P8.1）：目标选择器 + Configure / Build / Run / Test。
 *
 * 仅当项目含根级 CMakeLists.txt 时显示。目标列表来自后端真实 CMake
 * File API 发现（沙箱内 Configure），不做任何本地猜测；构建/运行/测试
 * 输出全部进入现有终端面板。
 */

import { useCallback, useMemo, useState } from 'react'
import { Button } from '../ui/Button'
import { Badge } from '../ui/Badge'
import { useRunStore } from '../../stores/runStore'
import {
  cmakeBuildInTerminal,
  cmakeDiscoverInTerminal,
  cmakeRunInTerminal,
  cmakeTestInTerminal,
} from '../../lib/runner/runCmake'
import type { CmakeTarget } from '../../api/executions'
import type { FileMeta } from '../../types/file'

interface CMakeControlsProps {
  projectId: string
  files: FileMeta[] | null
  /** 编辑器草稿优先的完整文件快照（与「运行当前文件」同一 VFS 来源）。 */
  buildVfs: () => Promise<Map<string, string> | null>
  onRevealTerminal: () => void
}

const TYPE_LABELS: Record<string, string> = {
  EXECUTABLE: '可执行',
  STATIC_LIBRARY: '静态库',
  SHARED_LIBRARY: '动态库',
  OBJECT_LIBRARY: '对象库',
  INTERFACE_LIBRARY: '接口库',
  UTILITY: '工具目标',
}

export function CMakeControls({ projectId, files, buildVfs, onRevealTerminal }: CMakeControlsProps) {
  const running = useRunStore((state) => state.running)
  const [targets, setTargets] = useState<CmakeTarget[]>([])
  const [selected, setSelected] = useState('')
  const [profile, setProfile] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const isCMakeProject = files?.some((file) => file.path === 'CMakeLists.txt') ?? false

  const orderedTargets = useMemo(() => {
    if (!targets.length) return []
    return [...targets].sort((a, b) => Number(b.runnable) - Number(a.runnable))
  }, [targets])
  const selectedTarget = targets.find((t) => t.name === selected) ?? null

  const discover = useCallback(async () => {
    setBusy(true)
    onRevealTerminal()
    try {
      const vfs = await buildVfs()
      if (!vfs) {
        useRunStore.getState().appendEntry('error', '✘ 无法读取项目文件（VFS 构建失败）')
        return
      }
      const outcome = await cmakeDiscoverInTerminal(vfs, projectId)
      if (outcome.ok && outcome.targets.length > 0) {
        setTargets(outcome.targets)
        setSelected((prev) => {
          const keep = outcome.targets.find((t) => t.name === prev)
          if (keep) return prev
          const firstExe = outcome.targets.find((t) => t.runnable)
          return firstExe?.name ?? ''
        })
        setProfile(
          `CMake · Debug · Clang 15${outcome.cmakeVersion ? ` · ${outcome.cmakeVersion}` : ''}`,
        )
      }
    } finally {
      setBusy(false)
    }
  }, [projectId, buildVfs, onRevealTerminal])

  const withVfs = useCallback(
    async (run: (vfs: Map<string, string>) => Promise<unknown>) => {
      setBusy(true)
      onRevealTerminal()
      try {
        const vfs = await buildVfs()
        if (!vfs) {
          useRunStore.getState().appendEntry('error', '✘ 无法读取项目文件（VFS 构建失败）')
          return
        }
        await run(vfs)
      } finally {
        setBusy(false)
      }
    },
    [buildVfs, onRevealTerminal],
  )

  if (!isCMakeProject) return null

  const disabled = running || busy

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-edge-soft bg-panel-2 px-4 py-1.5 text-xs">
      <Badge tone="info">{profile ?? 'CMake · 未配置'}</Badge>

      <select
        aria-label="选择 CMake 目标"
        className="h-6 rounded border border-edge-soft bg-panel px-1.5 text-xs"
        value={selected}
        onChange={(event) => setSelected(event.target.value)}
        disabled={disabled || orderedTargets.length === 0}
      >
        {orderedTargets.length === 0 && <option value="">（未发现目标——先 Configure）</option>}
        {orderedTargets.map((target) => (
          <option key={target.name} value={target.name}>
            {target.name}（{TYPE_LABELS[target.type] ?? target.type}
            {target.runnable ? '' : ' · 仅构建'}）
          </option>
        ))}
      </select>

      <div className="flex items-center gap-1.5">
        <Button size="sm" variant="outline" disabled={disabled} onClick={() => void discover()}>
          {targets.length > 0 ? '刷新目标' : 'Configure'}
        </Button>
        <Button
          size="sm" variant="outline" disabled={disabled || !selected}
          onClick={() => void withVfs((vfs) => cmakeBuildInTerminal(vfs, selected, projectId))}
        >
          构建目标
        </Button>
        <Button
          size="sm" disabled={disabled || !selectedTarget?.runnable}
          title={selectedTarget && !selectedTarget.runnable
            ? `目标 ${selectedTarget.name} 是 ${TYPE_LABELS[selectedTarget.type] ?? selectedTarget.type}，不可运行` : undefined}
          onClick={() => void withVfs((vfs) => cmakeRunInTerminal(vfs, selected, projectId))}
        >
          运行目标
        </Button>
        <Button
          size="sm" variant="outline" disabled={disabled}
          onClick={() => void withVfs((vfs) => cmakeTestInTerminal(vfs, projectId))}
        >
          运行测试（CTest）
        </Button>
      </div>

      {selectedTarget && selectedTarget.dependencies.length > 0 && (
        <span className="text-ink-faint">
          链接：{selectedTarget.dependencies.join(', ')}
        </span>
      )}
    </div>
  )
}
