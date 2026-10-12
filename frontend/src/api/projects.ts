/** projects 资源 API：所有响应经 zod 校验后返回。 */

import { api } from './client'
import {
  projectListSchema,
  projectReadSchema,
  type Project,
  type ProjectCreateInput,
} from '../types/project'

export async function listProjects(): Promise<Project[]> {
  const data = await api.get<unknown>('/projects')
  const parsed = projectListSchema.parse(data)
  return parsed.items
}

export async function getProject(id: string): Promise<Project> {
  const data = await api.get<unknown>(`/projects/${id}`)
  return projectReadSchema.parse(data)
}

export async function createProject(input: ProjectCreateInput): Promise<Project> {
  const data = await api.post<unknown>('/projects', input)
  return projectReadSchema.parse(data)
}

/** 删除项目（后端级联删除文件/任务/计划/事件，204）。 */
export async function deleteProject(id: string): Promise<void> {
  await api.delete<unknown>(`/projects/${id}`)
}
