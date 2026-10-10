/** 前端类型契约测试：确保 zod schema 与后端 Pydantic 契约一致。 */
import { describe, expect, it } from 'vitest'
import {
  milestoneSchema,
  projectListSchema,
  projectReadSchema,
} from '../types/project'

const validProject = {
  id: '0e0f26b4-7e4d-4c8f-9d3a-2f4f5c6a7b8d',
  ownerId: 'dev-user',
  title: 'Markdown 笔记编辑器',
  description: '带实时预览的笔记应用',
  mode: 'rebuild',
  status: 'draft',
  complexity: 'medium',
  targetFeatures: ['实时预览', '本地保存'],
  nonGoals: ['插件系统'],
  stack: ['TypeScript', 'React'],
  milestones: [
    { id: 'm1', title: '页面骨架', description: '', status: 'pending' },
    { id: 'm2', title: '实时预览', status: 'in-progress' },
  ],
  acceptanceCriteria: [],
  specVersion: 1,
  createdAt: '2026-10-10T03:00:00Z',
  updatedAt: '2026-10-10T03:00:00Z',
}

describe('projectReadSchema', () => {
  it('解析合法的项目响应', () => {
    const project = projectReadSchema.parse(validProject)
    expect(project.title).toBe('Markdown 笔记编辑器')
    expect(project.milestones).toHaveLength(2)
    expect(project.milestones[1].description).toBe('') // default 生效
  })

  it('拒绝非法的 mode / status / 非 UUID id', () => {
    expect(() => projectReadSchema.parse({ ...validProject, mode: 'unknown' })).toThrow()
    expect(() => projectReadSchema.parse({ ...validProject, status: 'deleted' })).toThrow()
    expect(() => projectReadSchema.parse({ ...validProject, id: 'not-a-uuid' })).toThrow()
  })

  it('拒绝缺失必需字段', () => {
    const { specVersion: _omit, ...incomplete } = validProject
    expect(() => projectReadSchema.parse(incomplete)).toThrow()
  })
})

describe('milestoneSchema', () => {
  it('status 应用默认值 pending', () => {
    const milestone = milestoneSchema.parse({ id: 'm1', title: '骨架' })
    expect(milestone.status).toBe('pending')
  })
})

describe('projectListSchema', () => {
  it('解析列表响应', () => {
    const list = projectListSchema.parse({ items: [validProject], total: 1 })
    expect(list.total).toBe(1)
    expect(list.items[0].id).toBe(validProject.id)
  })
})
