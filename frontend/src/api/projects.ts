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
