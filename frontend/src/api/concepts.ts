/** 知识概念 API。 */

import { api } from './client'
import { conceptListSchema, conceptReadSchema, type Concept } from '../types/concept'

export interface ConceptListResult {
  items: Concept[]
  domains: string[]
}

export async function listConcepts(domain?: string): Promise<ConceptListResult> {
  const query = domain ? `?domain=${encodeURIComponent(domain)}` : ''
  const data = await api.get<unknown>(`/concepts${query}`)
  const parsed = conceptListSchema.parse(data)
  return { items: parsed.items, domains: parsed.domains }
}

export async function getConcept(id: string): Promise<Concept> {
  const data = await api.get<unknown>(`/concepts/${encodeURIComponent(id)}`)
  return conceptReadSchema.parse(data)
}
