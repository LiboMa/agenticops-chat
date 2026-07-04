/** Nav 排序自愈:stored ∩ current 保序,current 新增项 append(版本升级安全)。 */
export function reorderNavIds(stored: string[], current: string[]): string[] {
  const currentSet = new Set(current);
  const kept = stored.filter((id) => currentSet.has(id));
  const keptSet = new Set(kept);
  return [...kept, ...current.filter((id) => !keptSet.has(id))];
}

/** 把 sourceId 移到 targetId 之前;任一 id 不存在或相同则原样返回。 */
export function moveId(order: string[], sourceId: string, targetId: string): string[] {
  if (sourceId === targetId) return order;
  const si = order.indexOf(sourceId);
  const ti = order.indexOf(targetId);
  if (si === -1 || ti === -1) return order;
  const next = order.filter((id) => id !== sourceId);
  next.splice(next.indexOf(targetId), 0, sourceId);
  return next;
}
