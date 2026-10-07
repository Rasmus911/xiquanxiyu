interface CatalogIdentity { id: string; kind: string }
export function togglePackageSelection(selection: Record<string,number>, catalog: CatalogIdentity[], itemId: string) {
  if (!catalog.some(item=>item.id===itemId && item.kind==='package')) throw new Error('套票不存在')
  const next={...selection}
  for (const item of catalog) if(item.kind==='package') delete next[item.id]
  if(!selection[itemId]) next[itemId]=1
  return next
}
