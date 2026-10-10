/**
 * 任务面板（P4.1）：当前任务详情 + 任务测试运行 + 逐用例反馈。
 * 挂载于 IDE 左侧"任务"页签（LeftPanel），由 IdePage 提供 plan tasks 与文件上下文。
 */
import { useCallback, useEffect, useState } from 'react'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import type { PlanTask } from '../../types/plan'
import type { EvaluationResult, EvaluationFileResult } from '../../api/tasks'
import type { TestFileResult } from '../../types/runner'
import { evaluateTask } from '../../api/tasks'
import { useRunStore } from '../../stores/runStore'

const STATUS_LABELS: Record<string, { text: string; tone: 'ok' | 'danger' | 'info' | 'neutral' }> = {
  done: { text: '已完成', tone: 'ok' },
  'needs-fix': { text: '需修正', tone: 'danger' },
  'in-progress': { text: '进行中', tone: 'info' },
  pending: { text: '待开始', tone: 'neutral' },
}

export interface TaskPanelProps {
  projectId: string
  tasks: PlanTask[]
  /** 当前选中的任务 ID */
  currentTaskId: string | null
  onSelectTask: (taskId: string) => void
  /** 运行任务绑定的测试（浏览器 Worker，返回逐文件结果） */
  onRunTaskTests: (testPaths: string[]) => Promise<TestFileResult[]>
}

export function TaskPanel({
  projectId,
  tasks,
  currentTaskId,
  onSelectTask,
  onRunTaskTests,
}: TaskPanelProps) {
  const [evaluation, setEvaluation] = useState<EvaluationResult | null>(null)
  const [testResults, setTestResults] = useState<TestFileResult[]>([])
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const currentTask = tasks.find((t) => t.taskId === currentTaskId) ?? null
  const nextTask = tasks.find((t) => t.status === 'pending' && t.taskId !== currentTaskId) ?? null

  const runTests = useCallback(async () => {
    if (!currentTask || running) return
    setRunning(true)
    setError(null)
    setEvaluation(null)
    try {
      const results = await onRunTaskTests(currentTask.testFiles)
      setTestResults(results)
      const trace = useRunStore.getState().trace
      const files: EvaluationFileResult[] = results.map((r) => ({
        path: r.path,
        status: r.status,
        passed: r.cases.filter((c) => c.status === 'passed').length,
        failed: r.cases.filter((c) => c.status !== 'passed').length,
        totalCases: r.cases.length,
      }))
      const result = await evaluateTask(projectId, currentTask.taskId, {
        files,
        traceId: trace?.traceId ?? null,
        // executionId 存在 = 服务端沙箱执行（python/cpp），否则浏览器 Worker
        source: trace?.executionId ? 'remote' : 'browser',
        executionId: trace?.executionId ?? null,
      })
      setEvaluation(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : '任务测试运行失败')
    } finally {
      setRunning(false)
    }
  }, [currentTask, running, projectId, onRunTaskTests])

  // 任务切换时清空上一次的反馈
  useEffect(() => {
    setEvaluation(null)
    setTestResults([])
    setError(null)
  }, [currentTaskId])

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* 任务列表 */}
      <div className="shrink-0 border-b border-edge-soft p-2">
        <div className="mb-1.5 text-[11px] font-medium text-ink-faint">
          学习任务（{tasks.filter((t) => t.status === 'done').length}/{tasks.length} 已完成）
        </div>
        <ul className="space-y-1">
          {tasks.map((task) => {
            const isActive = task.taskId === currentTaskId
            const meta = STATUS_LABELS[task.status] ?? STATUS_LABELS.pending
            return (
              <li key={task.taskId}>
                <button
                  type="button"
                  onClick={() => onSelectTask(task.taskId)}
                  className={`flex w-full items-center justify-between gap-2 rounded px-2 py-1.5 text-left text-xs transition-colors ${
                    isActive ? 'bg-accent-soft text-ink' : 'text-ink-dim hover:bg-panel-2 hover:text-ink'
                  }`}
                >
                  <span className="min-w-0 truncate">
                    <span className="mr-1.5 font-mono text-[10px] text-ink-faint">M{task.milestone}</span>
                    {task.title}
                  </span>
                  <Badge tone={meta.tone}>{meta.text}</Badge>
                </button>
              </li>
            )
          })}
        </ul>
      </div>

      {/* 当前任务详情 */}
      {currentTask ? (
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
          <div>
            <h3 className="text-sm font-semibold text-ink">{currentTask.title}</h3>
            <p className="mt-1 text-xs leading-relaxed text-ink-dim">{currentTask.description}</p>
          </div>

          {currentTask.deliverable && (
            <div>
              <div className="mb-1 text-[11px] font-medium text-ink-faint">交付目标</div>
              <p className="text-xs text-ink-dim">{currentTask.deliverable}</p>
            </div>
          )}

          {currentTask.acceptanceCriteria.length > 0 && (
            <div>
              <div className="mb-1 text-[11px] font-medium text-ink-faint">验收条件</div>
              <ul className="space-y-0.5">
                {currentTask.acceptanceCriteria.map((criteria, i) => (
                  <li key={i} className="text-xs leading-relaxed text-ink-dim">
                    · {criteria}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {currentTask.requiredConcepts.length > 0 && (
            <div>
              <div className="mb-1 text-[11px] font-medium text-ink-faint">涉及知识点</div>
              <div className="flex flex-wrap gap-1">
                {currentTask.requiredConcepts.map((concept) => (
                  <Badge key={concept}>{concept}</Badge>
                ))}
              </div>
            </div>
          )}

          {currentTask.testFiles.length > 0 && (
            <div>
              <div className="mb-1 text-[11px] font-medium text-ink-faint">任务测试文件</div>
              <div className="font-mono text-[11px] text-ink-faint">
                {currentTask.testFiles.join('、')}
              </div>
            </div>
          )}

          <Button
            size="sm"
            onClick={() => void runTests()}
            disabled={running || currentTask.testFiles.length === 0}
            className="w-full"
          >
            {running ? '测试运行中…' : '▶ 运行任务测试并验收'}
          </Button>

          {error && (
            <p role="alert" className="rounded border border-danger/40 bg-danger/10 px-2.5 py-2 text-xs text-danger">
              {error}
            </p>
          )}

          {/* 逐用例反馈 */}
          {testResults.length > 0 && (
            <div className="space-y-2">
              <div className="text-[11px] font-medium text-ink-faint">测试结果</div>
              {testResults.map((file) => (
                <div key={file.path} className="rounded border border-edge-soft">
                  <div className="flex items-center justify-between border-b border-edge-soft px-2.5 py-1.5">
                    <span className="truncate font-mono text-[11px] text-ink-dim">{file.path}</span>
                    <span className={`text-[11px] ${file.status === 'passed' ? 'text-ok' : 'text-danger'}`}>
                      {file.status === 'passed' ? '✔ 全部通过' : '✘ 有失败'}
                    </span>
                  </div>
                  <ul>
                    {file.cases.map((testCase, i) => (
                      <li key={i} className="border-b border-edge-soft/50 px-2.5 py-1 last:border-b-0">
                        <div className="flex items-start justify-between gap-2">
                          <span className={`text-[11px] ${testCase.status === 'passed' ? 'text-ok' : 'text-danger'}`}>
                            {testCase.status === 'passed' ? '✔' : '✘'} {testCase.name}
                          </span>
                        </div>
                        {testCase.error && (
                          <div className="mt-0.5 whitespace-pre-wrap break-all rounded bg-danger/10 px-1.5 py-1 text-[10px] text-danger">
                            {testCase.error}
                          </div>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}

          {/* 验收结果 */}
          {evaluation && (
            <div className={`rounded border px-3 py-2.5 text-xs ${evaluation.passed ? 'border-ok/40 bg-ok/10' : 'border-danger/40 bg-danger/10'}`}>
              <div className={`font-medium ${evaluation.passed ? 'text-ok' : 'text-danger'}`}>
                {evaluation.passed ? '✅ 练习通过' : '❌ 需要修正'}
              </div>
              <p className="mt-1 text-[11px] leading-relaxed text-ink-faint">
                信任级：{evaluation.trustLevel === 'practice' ? '练习（客户端自报，非正式验收）' : evaluation.trustLevel}
              </p>
              {evaluation.warnings.length > 0 && (
                <ul className="mt-1 space-y-0.5">
                  {evaluation.warnings.map((w, i) => (
                    <li key={i} className="text-[11px] text-warn">⚠ {w}</li>
                  ))}
                </ul>
              )}
              {evaluation.evidenceConcepts.length > 0 && (
                <p className="mt-1 text-[11px] text-ink-faint">
                  已记录学习证据：{evaluation.evidenceConcepts.join('、')}
                </p>
              )}
            </div>
          )}

          {/* 下一步引导 */}
          {evaluation?.passed && nextTask && (
            <button
              type="button"
              onClick={() => onSelectTask(nextTask.taskId)}
              className="w-full rounded-md border border-accent/40 bg-accent-soft px-3 py-2 text-xs text-ink transition-colors hover:bg-accent/20"
            >
              下一个任务：{nextTask.title} →
            </button>
          )}
        </div>
      ) : (
        <div className="flex flex-1 items-center justify-center p-4 text-center text-xs leading-relaxed text-ink-faint">
          选择一个任务开始学习。系统会展示任务说明、验收条件，并提供任务测试运行。
        </div>
      )}
    </div>
  )
}
