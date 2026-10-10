import type { Concept } from '../types/concept'

/** 只连接服务器已提供的先修节点，不补造缺失关系。 */
export function conceptEdges(concepts: Concept[]) {
  const ids = new Set(concepts.map((c) => c.id))
  return concepts.flatMap((c) => c.prerequisites.filter((id) => ids.has(id)).map((id) => ({ id: `${id}->${c.id}`, source: id, target: c.id })))
}
