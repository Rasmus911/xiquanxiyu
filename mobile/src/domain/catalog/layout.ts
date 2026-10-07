export function moveBefore(ids: string[], source: string, target: string): string[] {
  if (source === target || !ids.includes(source) || !ids.includes(target)) return [...ids]
  const next = ids.filter(id => id !== source)
  next.splice(next.indexOf(target), 0, source)
  return next
}
