/** Nav 排序自愈:stored ∩ current 保序;current 新增项插在默认顺序里它前面最近的已有项之后(没有就放最前),
 *  所以升级新增的入口出现在设计的位置,而不是排到最后;用户拖动一次后 stored 含它,之后以 stored 为准。
 *  renamed:旧 id → 接替它的新 id,新 id 就地占旧 id 的位置(升级后用户自定义的顺序不乱)。 */
export function reorderNavIds(stored: string[], current: string[], renamed: Record<string, string[]> = {}): string[] {
  const currentSet = new Set(current);
  const order = [...new Set(stored.flatMap((id) => renamed[id] ?? [id]))].filter((id) => currentSet.has(id));
  current.forEach((id, i) => {
    if (order.includes(id)) return;
    let at = 0;
    for (let j = i - 1; j >= 0; j--) {
      const k = order.indexOf(current[j]);
      if (k !== -1) { at = k + 1; break; }
    }
    order.splice(at, 0, id);
  });
  return order;
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
