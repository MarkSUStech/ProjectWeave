import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '../ui/Button'
import { createProject } from '../../api/projects'
import { ApiError } from '../../api/client'
import type { ProjectComplexity, ProjectMode } from '../../types/project'

const inputClass =
  'w-full rounded-md border border-edge bg-panel-2 px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-accent/60 focus:outline-none'
const labelClass = 'mb-1.5 block text-xs font-medium text-ink-dim'

export function CreateProjectForm({ onDone }: { onDone?: () => void }) {
  const navigate = useNavigate()
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [mode, setMode] = useState<ProjectMode>('rebuild')
  const [complexity, setComplexity] = useState<ProjectComplexity>('small')
  const [stackText, setStackText] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (!title.trim() || submitting) return
    setSubmitting(true)
    setError(null)
    const stack = stackText
      .split(/[,，]/)
      .map((item) => item.trim())
      .filter((item) => item.length > 0)
    try {
      const project = await createProject({
        title: title.trim(),
        description: description.trim(),
        mode,
        complexity,
        stack,
      })
      onDone?.()
      navigate(`/projects/${project.id}`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '创建项目失败，请稍后重试。')
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label htmlFor="project-title" className={labelClass}>
          项目目标 <span className="text-danger">*</span>
        </label>
        <input
          id="project-title"
          className={inputClass}
          placeholder="例如：做一个类似 Obsidian 的 Markdown 笔记编辑器"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          maxLength={200}
          required
        />
      </div>
      <div>
        <label htmlFor="project-description" className={labelClass}>
          补充描述
        </label>
        <textarea
          id="project-description"
          className={`${inputClass} min-h-24 resize-y`}
          placeholder="想解决什么问题？期望先实现哪些功能？"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          maxLength={8000}
        />
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <label htmlFor="project-mode" className={labelClass}>
            项目模式
          </label>
          <select
            id="project-mode"
            className={inputClass}
            value={mode}
            onChange={(e) => setMode(e.target.value as ProjectMode)}
          >
            <option value="rebuild">从零重建（Rebuild）</option>
            <option value="contribution">开源贡献（Contribution）</option>
          </select>
        </div>
        <div>
          <label htmlFor="project-complexity" className={labelClass}>
            预期复杂度
          </label>
          <select
            id="project-complexity"
            className={inputClass}
            value={complexity}
            onChange={(e) => setComplexity(e.target.value as ProjectComplexity)}
          >
            <option value="small">小</option>
            <option value="medium">中</option>
            <option value="large">大</option>
          </select>
        </div>
      </div>
      <div>
        <label htmlFor="project-stack" className={labelClass}>
          技术栈（逗号分隔）
        </label>
        <input
          id="project-stack"
          className={inputClass}
          placeholder="TypeScript, React, Vite"
          value={stackText}
          onChange={(e) => setStackText(e.target.value)}
        />
      </div>

      {error && (
        <p role="alert" className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger">
          {error}
        </p>
      )}

      <div className="flex justify-end">
        <Button type="submit" disabled={!title.trim() || submitting}>
          {submitting ? '创建中…' : '创建项目'}
        </Button>
      </div>
      <p className="text-xs leading-relaxed text-ink-faint">
        创建后可进入真实教学 IDE，完成能力诊断并生成样板课程学习路线。AI 需求分析未实现（P4）。
      </p>
    </form>
  )
}
