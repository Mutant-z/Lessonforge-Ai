export function normalizeSlideIndex(index: number | undefined | null, total: number): number {
  if (total <= 0) return 0;
  const numeric = Number(index);
  if (!Number.isFinite(numeric)) return 0;
  return Math.min(total - 1, Math.max(0, Math.trunc(numeric)));
}

export function updateSlideSelection(current: Set<number>, index: number, additive: boolean): Set<number> {
  const next = new Set(additive ? current : []);
  if (additive && next.has(index)) next.delete(index);
  else next.add(index);
  return next;
}
