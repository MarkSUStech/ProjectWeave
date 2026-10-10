/** 学习者模型 API。 */

import { api } from './client'
import { masteryListSchema, type Mastery } from '../types/mastery'

export async function listMastery(): Promise<Mastery[]> {
  const data = await api.get<unknown>('/mastery')
  return masteryListSchema.parse(data).items
}
