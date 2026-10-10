import { useCallback, useEffect, useMemo, useState } from 'react'
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
import { TerminalView, TestView, EventsView } from '../components/ide/BottomPanel'
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
import { runRemoteInTerminal, runRemoteTestsInTerminal, canRunPath, isAnyTestPath, isRemoteExecutable } from '../lib/runner/runRemote'
import { detectLanguage } from '../lib/execution/LanguageProfile'
import { trackClientEvent } from '../lib/eventTracker'
import { fetchSuggestion } from '../api/tutor'
import type { TutorDecision } from '../types/tutor'
import { WorkspaceLayout } from '../components/ide/WorkspaceLayout'
import { WorkspaceLayoutProvider, useWorkspaceLayout } from '../components/ide/WorkspaceLayoutContext'
import { WorkspaceViewMenu } from '../components/ide/WorkspaceViewMenu'
import { CommandPalette } from '../components/ide/CommandPalette'
import { WorkspaceNoticeStrip } from '../components/ide/WorkspaceNoticeStrip'
import { TaskPanel } from '../components/ide/TaskPanel'
import type { PatchApplyResult } from '../lib/workspace/executor'
import type { PlanTask } from '../types/plan'
import type { TestFileResult } from '../types/runner'
import { getPlan } from '../api/plans'
import { readFile } from '../api/files'
import { AnimatePresence, motion } from 'motion/react'
import { useUiReducedMotion } from '../hooks/useUiReducedMotion'
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
  return <WorkspaceLayoutProvider><IdeWorkspace key={project.id} project={project} /></WorkspaceLayoutProvider>
}

function IdeWorkspace({ project }: { project: Project }) {
  const layout = useWorkspaceLayout()
  const reduced = useUiReducedMotion()
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

  // P4.1：加载学习计划任务（含 testFiles/acceptanceCriteria）
  const [planTasks, setPlanTasks] = useState<PlanTask[] | null>(null)
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(null)
  const loadPlanTasks = useCallback(async () => {
    try {
      const detail = await getPlan(project.id)
      setPlanTasks(detail.tasks)
      // 默认选中第一个未完成任务
      setCurrentTaskId((prev) => {
        if (prev && detail.tasks.some((t) => t.taskId === prev)) return prev
        const next = detail.tasks.find((t) => t.status !== 'done')
        return next?.taskId ?? detail.tasks[0]?.taskId ?? null
      })
    } catch {
      setPlanTasks([])
    }
  }, [project.id])
  useEffect(() => {
    void loadPlanTasks()
  }, [loadPlanTasks])

  // 任务测试运行：通过统一执行层（P4.2a 语言无关架构）。
  // 构建 VFS → execute() → 按语言路由（TS → browser-worker / Python → remote-pytest）。
  const buildProjectVfs = useCallback(async (): Promise<Map<string, string> | null> => {
    const vfs = new Map<string, string>()
    if (!files) return null
    for (const file of files) {
      try {
        const content = openPath === file.path ? draftContent : (await readFile(project.id, file.path)).content
        vfs.set(file.path, content)
      } catch { /* 文件读取失败不阻塞其他文件 */ }
    }
    return vfs
  }, [project.id, openPath, draftContent, files])

  const runTaskTests = useCallback(
    async (testPaths: string[]): Promise<TestFileResult[]> => {
      const vfs = await buildProjectVfs()
      if (!vfs) return []

      const { execute, UnsupportedExecutionError, detectLanguage } = await import('../lib/execution')
      const languageId = detectLanguage(testPaths[0] ?? '') ?? 'typescript'
      try {
        const result = await execute({
          mode: 'test',
          testPaths,
          files: vfs,
          languageId,
          stdin: languageId === 'python' ? useRunStore.getState().stdin || undefined : undefined,
        })
        // 输出到终端（构建信息 + 测试输出）
        if (result.buildTimeMs > 0) {
          useRunStore.getState().appendEntry('system', `模块打包 ${result.buildTimeMs}ms（${result.modules.length} 个模块）`)
        }
        for (const out of result.output) {
          useRunStore.getState().appendEntry(out.level, out.text)
        }
        for (const diag of result.buildDiagnostics) {
          useRunStore.getState().appendEntry('error', `[构建] ${diag.file ? `${diag.file}: ` : ''}${diag.message}`)
        }
        return (result.testResults ?? []).map((file) => ({
          path: file.path,
          status: file.status,
          error: file.error,
          cases: file.cases.map((c) => ({
            name: c.name, status: c.status, error: c.error, durationMs: c.durationMs,
          })),
        }))
      } catch (err) {
        if (err instanceof UnsupportedExecutionError) {
          useRunStore.getState().appendEntry('error', err.message)
        }
        return testPaths.map((path) => ({
          path, status: 'error' as const,
          error: err instanceof Error ? err.message : String(err),
          cases: [],
        }))
      }
    },
    [buildProjectVfs],
  )

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
    // 远程语言（Python/C++）：测试文件走远程沙箱；TS 项目维持浏览器套件。
    const remoteTests = files.filter((f) => isRemoteExecutable(f.path) && isAnyTestPath(f.path))
    if (remoteTests.length > 0) {
      layout?.reveal('tests')
      useTestStore.getState().setRunning(true)
      useTestStore.getState().resetResults(remoteTests.length)
      const language = detectLanguage(remoteTests[0].path) ?? 'python'
      try {
        const outcome = await runRemoteTestsInTerminal(
          remoteTests.map((f) => f.path),
          (await buildProjectVfs()) ?? new Map(),
          { projectId: project.id },
        )
        // 会话快照里的逐文件结果写回测试面板
        const { getExecution } = await import('../api/executions')
        if (outcome.executionId) {
          const snap = await getExecution(outcome.executionId)
          for (const file of snap.testResults ?? []) {
            useTestStore.getState().appendFileResult({
              path: file.path,
              status: file.status,
              error: file.error ?? undefined,
              cases: file.cases.map((c) => ({
                name: c.name,
                status: c.status === 'passed' ? ('passed' as const) : ('failed' as const),
                error: c.error ?? undefined,
                durationMs: c.durationMs,
              })),
            })
          }
        }
        const results = useTestStore.getState().results
        const totalCases = results.reduce((sum, f) => sum + f.cases.length, 0)
        const failed = results.reduce((sum, f) => sum + f.cases.filter((c) => c.status !== 'passed').length, 0)
        trackClientEvent(
          'tests-run',
          { files: remoteTests.length, passed: totalCases - failed, failed, traceId: outcome.traceId, language },
          { projectId: project.id },
        )
        void maybeFetchSuggestion(failed > 0)
      } finally {
        useTestStore.getState().setRunning(false)
      }
      return
    }
    layout?.reveal('tests')
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
  }, [project.id, files, openPath, draftContent, maybeFetchSuggestion, layout, buildProjectVfs])

  const handleRun = useCallback(() => {
    if (!openPath || !files) return
    // 测试文件：运行项目全部测试（当前文件草稿优先）；普通文件：运行当前内容。
    if (isAnyTestPath(openPath)) {
      void handleRunTests()
      return
    }
    // 远程语言（Python/C++）：沙箱执行；测试文件（test_*.py / *_test.cpp）走远程测试。
    if (isRemoteExecutable(openPath)) {
      const isRemoteTest = isAnyTestPath(openPath)
      const language = detectLanguage(openPath) ?? 'python'
      const startedAt = Date.now()
      layout?.reveal('terminal')
      void buildProjectVfs().then((vfs) => {
        if (!vfs) {
          useRunStore.getState().appendEntry('error', '✘ 无法读取项目文件（VFS 构建失败）')
          return { status: 'error' as const, traceId: null, executionId: null, exitCode: null, ok: false }
        }
        const options = { projectId: project.id }
        return isRemoteTest ? runRemoteTestsInTerminal([openPath], vfs, options) : runRemoteInTerminal(openPath, vfs, options)
      }).then((outcome) => {
        trackClientEvent(
          isRemoteTest ? 'tests-run' : 'code-run',
          { path: openPath, status: outcome.status, durationMs: Date.now() - startedAt, traceId: outcome.traceId, language },
          { projectId: project.id },
        )
        void maybeFetchSuggestion(outcome.status !== 'ok')
      })
      return
    }
    const startedAt = Date.now()
    layout?.reveal('terminal')
    void runFileInTerminal(openPath, draftContent).then(({ status, traceId }) => {
      trackClientEvent('code-run', { path: openPath, status, durationMs: Date.now() - startedAt, traceId }, { projectId: project.id })
      void maybeFetchSuggestion(status !== 'ok')
    })
  }, [project.id, openPath, draftContent, files, handleRunTests, maybeFetchSuggestion, layout, buildProjectVfs])

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

  // Mentor 上下文：最近一次运行的真实失败摘要（编译诊断/traceback 来自终端条目，
  // 语言无关——TS/Python/C++ 的错误行都会以 error 条目出现）。
  const terminalEntries = useRunStore((s) => s.entries)
  const mentorRunSummary = useMemo(() => {
    if (terminalEntries.length === 0) return null
    const lastRunIdx = terminalEntries.reduce(
      (acc, e, i) => (e.kind === 'system' && e.text.startsWith('▶') ? i : acc), -1)
    const slice = terminalEntries.slice(lastRunIdx >= 0 ? lastRunIdx + 1 : -15)
    if (slice.length === 0) return null
    const hasError = slice.some((e) => e.kind === 'error')
    const summary = slice
      .slice(-10)
      .map((e) => e.text)
      .join('\n')
      .slice(0, 600)
    return { status: hasError ? 'error' : 'ok', summary }
  }, [terminalEntries])

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
  const handleOpenFile = (path: string) => { layout?.reveal('editor'); void openFile(path) }
  const resourceProps = { project, files, openPath, onOpenFile: handleOpenFile, onCreateFile: createFile,
    onRenameFile: renameFile, onDeleteFile: deleteFile, historyApi }

  return <div className="flex h-screen min-w-[960px] flex-col overflow-hidden bg-app">
    <IdeTopBar project={project} commands={<><CommandPalette files={files} onOpenFile={handleOpenFile}
      onSave={() => void save()} onRun={handleRun} canSave={!!openPath && dirty && !saving}
      canRun={!!openPath && canRunPath(openPath) && !running && !testsRunning} /><WorkspaceViewMenu /></>} />
    <WorkspaceNoticeStrip projectId={project.id} onApplyPatch={applyPatch} />
    <div className="min-h-0 flex-1">
      <WorkspaceLayout mode={mode} projectId={project.id} panels={{
        files: <LeftPanel {...resourceProps} view="files" />,
        tasks: planTasks !== null
          ? <TaskPanel projectId={project.id} tasks={planTasks} currentTaskId={currentTaskId}
              onSelectTask={setCurrentTaskId} onRunTaskTests={runTaskTests} />
          : <LeftPanel {...resourceProps} view="tasks" />,
        history: <LeftPanel {...resourceProps} view="history" />,
        editor: editorWithSuggestion, canvas,
        mentor: <MentorPanel projectId={project.id} currentFile={openPath ? { path: openPath, content: draftContent } : undefined}
          onApplyPatch={applyPatch} currentTaskId={currentTaskId}
          recentRunResult={mentorRunSummary} />,
        terminal: <TerminalView />, tests: <TestView onRun={() => void handleRunTests()} />,
        events: <EventsView projectId={project.id} />,
      }} />
    </div>
    <footer className="flex h-7 shrink-0 items-center justify-between border-t border-edge-soft bg-panel px-4 text-[11px] text-ink-faint">
      <span>ProjectWeave · 浏览器工作区</span><span>{files?.length ?? '…'} 个文件 · {dirty ? '有未保存更改' : '自动保存已开启'}</span>
    </footer>
  </div>
}
