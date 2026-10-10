import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getProject } from '../api/projects'
import { ApiError } from '../api/client'
import type { Project } from '../types'
import { ErrorBanner, Spinner } from '../components/ui/Feedback'
import { Button } from '../components/ui/Button'
import { IdeTopBar } from '../components/ide/IdeTopBar'
import { LeftPanel } from '../components/ide/LeftPanel'
import { EditorPanel } from '../components/ide/EditorPanel'
import { MentorPanel } from '../components/ide/MentorPanel'
import { BottomPanel } from '../components/ide/BottomPanel'
import { CanvasPlaceholder } from '../components/ide/CanvasPlaceholder'
import { SceneRenderer } from '../viz/SceneRenderer'
import { DEBUG_PANEL_SCENE, VARIABLES_STATE_SCENE } from '../viz/scenes'
import { fingerprint } from '../lib/fingerprint'
import { useIdeUiStore } from '../stores/ideUiStore'
import { useRunStore } from '../stores/runStore'
import { useTestStore } from '../stores/testStore'
import { useProjectFiles } from '../hooks/useProjectFiles'
import { useFileHistory } from '../hooks/useFileHistory'
import { runFileInTerminal } from '../lib/runner/runToTerminal'
import { runTestSuite } from '../lib/runner/runTestSuite'
import { isTestPath } from '../lib/runner/runFile'
import { trackClientEvent } from '../lib/eventTracker'
import { fetchSuggestion } from '../api/tutor'
import type { TutorDecision } from '../types/tutor'
import { WorkspaceLayout } from '../components/ide/WorkspaceLayout'
import { CommandPalette } from '../components/ide/CommandPalette'
import { WorkspaceNoticeStrip } from '../components/ide/WorkspaceNoticeStrip'
import type { PatchApplyResult } from '../lib/workspace/executor'
import { isRunnablePath } from '../lib/runner/runFile'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { formatDateTime } from '../lib/labels'

/**
 * 教学 IDE（P1.1/P1.2）：文件树与编辑器接入服务器端文件系统。
 * 布局随工作模式切换；布局锁定后不可切换；其余面板为标注清晰的占位。
 */
export default function IdePage() {
  const { id } = useParams<{ id: string }>()
  const [project, setProject] = useState<Project | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!id) return
    setError(null)
    try {
      setProject(await getProject(id))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '未知错误')
    }
  }, [id])

  useEffect(() => {
    void load()
  }, [load])

  if (error) {
    return (
      <div className="grid min-h-full place-items-center px-6">
        <div className="w-full max-w-md space-y-4 text-center">
          <ErrorBanner message={error} onRetry={() => void load()} />
          <Link to="/">
            <Button variant="outline">返回项目列表</Button>
          </Link>
        </div>
      </div>
    )
  }
  if (!project) {
    return <Spinner label="正在加载工作台…" />
  }
  return <IdeWorkspace project={project} />
}

function IdeWorkspace({ project }: { project: Project }) {
  const reduced = useReducedMotion()
  const mode = useIdeUiStore((state) => state.mode)
  const running = useRunStore((state) => state.running)
  const testsRunning = useTestStore((state) => state.running)
  const {
    files,
    treeError,
    openPath,
    draftContent,
    dirty,
    fileError,
    saving,
    openFile,
    setDraft,
    save,
    createFile,
    renameFile,
    deleteFile,
    reloadCurrent,
    refresh,
  } = useProjectFiles(project.id)

  const fileHistory = useFileHistory(project.id, openPath, files?.find((file) => file.path === openPath)?.updatedAt)

  const handleRestoreSnapshot = useCallback(
    async (snapshotId: string) => {
      const ok = await fileHistory.restore(snapshotId)
      if (!ok) return
      // 编辑器重读恢复后的内容，并刷新文件树元数据。
      await reloadCurrent()
      await refresh()
    },
    [fileHistory, reloadCurrent, refresh],
  )

  const historyApi = {
    currentContent: draftContent,
    history: fileHistory.history,
    error: fileHistory.error,
    preview: fileHistory.preview,
    previewLoading: fileHistory.previewLoading,
    restoring: fileHistory.restoring,
    onPreview: (snapshotId: string) => void fileHistory.loadPreview(snapshotId),
    onRestore: (snapshotId: string) => void handleRestoreSnapshot(snapshotId),
  }

  const lastSavedAt = (() => {
    const meta = files?.find((f) => f.path === openPath)
    if (!meta || dirty || saving) return null
    return formatDateTime(meta.updatedAt)
  })()

  const [suggestion, setSuggestion] = useState<TutorDecision | null>(null)

  const maybeFetchSuggestion = useCallback(
    async (failed: boolean) => {
      // 失败后按介入模式请求非阻塞建议（Quiet 时后端直接返回 null）；可忽略。
      if (!failed) return
      try {
        setSuggestion(await fetchSuggestion(project.id))
      } catch {
        // 建议是辅助信息，失败不打扰
      }
    },
    [project.id],
  )

  const handleRunTests = useCallback(async () => {
    if (!files) return
    const summary = await runTestSuite(project.id, files, {
      currentDraft: openPath ? { path: openPath, content: draftContent } : undefined,
    })
    const traceId = useRunStore.getState().trace?.traceId ?? null
    trackClientEvent(
      'tests-run',
      { files: summary.totalFiles, passed: summary.totalPassed, failed: summary.totalFailed, traceId },
      { projectId: project.id },
    )
    void maybeFetchSuggestion(summary.totalFailed > 0 || summary.errorFiles > 0)
  }, [project.id, files, openPath, draftContent, maybeFetchSuggestion])

  const handleRun = useCallback(() => {
    if (!openPath || !files) return
    // 测试文件：运行项目全部测试（当前文件草稿优先）；普通文件：运行当前内容。
    if (isTestPath(openPath)) {
      void handleRunTests()
      return
    }
    const startedAt = Date.now()
    void runFileInTerminal(openPath, draftContent).then(({ status, traceId }) => {
      trackClientEvent('code-run', { path: openPath, status, durationMs: Date.now() - startedAt, traceId }, { projectId: project.id })
      void maybeFetchSuggestion(status !== 'ok')
    })
  }, [project.id, openPath, draftContent, files, handleRunTests, maybeFetchSuggestion])

  // §14.3 过期判定：草稿指纹与最近一次"单文件运行"的指纹不一致 → 画布标记过期。
  // （测试套件 trace 的 runPath 为 null，不参与单文件比对。）
  const runTrace = useRunStore((state) => state.trace)
  const [draftFingerprint, setDraftFingerprint] = useState<string | null>(null)
  useEffect(() => {
    let cancelled = false
    if (openPath === null) {
      setDraftFingerprint(null)
      return
    }
    void fingerprint(openPath, draftContent).then((value) => {
      if (!cancelled) setDraftFingerprint(value)
    })
    return () => {
      cancelled = true
    }
  }, [openPath, draftContent])
  const canvasStale =
    runTrace !== null &&
    runTrace.runPath !== null &&
    runTrace.runPath === openPath &&
    draftFingerprint !== null &&
    runTrace.fingerprint !== draftFingerprint

  const editor = (
    <EditorPanel
      openPath={openPath}
      content={draftContent}
      dirty={dirty}
      saving={saving}
      error={fileError ?? treeError}
      lastSavedAt={lastSavedAt}
      running={running || testsRunning}
      onChange={setDraft}
      onSave={() => void save()}
      onRun={handleRun}
    />
  )

  const editorWithSuggestion = <div className="flex h-full min-h-0 flex-col">
    <AnimatePresence initial={false}>
      {suggestion && <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} transition={{ duration: reduced ? 0 : 0.2 }} className="shrink-0 overflow-hidden border-b border-warn/30 bg-warn/10">
        <div className="flex items-start justify-between gap-3 px-3 py-2">
          <div className="min-w-0 text-xs leading-relaxed text-ink-dim"><span className="mr-2 text-warn">AI 建议 · 非阻塞</span>{suggestion.message}</div>
          <Button size="sm" variant="ghost" onClick={() => setSuggestion(null)}>忽略</Button>
        </div>
      </motion.div>}
    </AnimatePresence>
    {editor}
  </div>
  const canvas = mode === 'architecture' ? <CanvasPlaceholder kind="architecture" /> :
    <SceneRenderer scene={mode === 'debugging' ? DEBUG_PANEL_SCENE : VARIABLES_STATE_SCENE} trace={runTrace} stale={canvasStale} />

  // A2 补丁应用守卫（§10.2 用户内容优先）：目标文件必须已打开且无未保存更改，
  // 防止 AI 补丁覆盖用户正在编辑的草稿（自动保存 2.5s 内的输入也受保护）。
  const applyPatch = useCallback(
    (path: string, content: string): PatchApplyResult => {
      if (openPath !== path) {
        return { applied: false, reason: `目标文件「${path}」当前未打开` }
      }
      if (dirty) {
        return { applied: false, reason: '当前有未保存的更改，请等待自动保存完成（或手动保存）后再应用' }
      }
      setDraft(content)
      return { applied: true }
    },
    [openPath, dirty, setDraft],
  )

  return <div className="flex h-screen min-w-[960px] flex-col overflow-hidden bg-app">
    <IdeTopBar project={project} commands={<CommandPalette files={files} onOpenFile={(path) => void openFile(path)}
      onSave={() => void save()} onRun={handleRun} canSave={!!openPath && dirty && !saving}
      canRun={!!openPath && isRunnablePath(openPath) && !running && !testsRunning} />} />
    <WorkspaceNoticeStrip projectId={project.id} onApplyPatch={applyPatch} />
    <div className="min-h-0 flex-1">
      <WorkspaceLayout mode={mode}
        left={<LeftPanel project={project} files={files} openPath={openPath} onOpenFile={(path) => void openFile(path)}
          onCreateFile={createFile} onRenameFile={renameFile} onDeleteFile={deleteFile} historyApi={historyApi} />}
        editor={editorWithSuggestion} canvas={canvas} mentor={<MentorPanel projectId={project.id} currentFile={openPath ? { path: openPath, content: draftContent } : undefined} onApplyPatch={applyPatch} />}
        bottom={<BottomPanel onRunTests={() => void handleRunTests()} projectId={project.id} />} />
    </div>
    <footer className="flex h-7 shrink-0 items-center justify-between border-t border-edge-soft bg-panel px-4 text-[11px] text-ink-faint">
      <span>ProjectWeave · 浏览器工作区</span><span>{files?.length ?? '…'} 个文件 · {dirty ? '有未保存更改' : '自动保存已开启'}</span>
    </footer>
  </div>
}
