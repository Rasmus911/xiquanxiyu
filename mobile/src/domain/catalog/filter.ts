export type CatalogFilterKind = 'all' | 'service' | 'product'
interface Filterable { id: string; kind: string; name: string; category: string; sort_order: number; is_active?: boolean }
export function visibleCatalog<T extends Filterable>(items: T[], filter: { kind: CatalogFilterKind; category: string; keyword: string }): T[] {
  return items.filter(item => item.is_active !== false && ['service', 'product', 'package'].includes(item.kind)
    && (filter.kind === 'all' || item.kind === filter.kind || (filter.kind === 'service' && item.kind === 'package'))
    && (!filter.category || item.category === filter.category)
    && (!filter.keyword.trim() || item.name.includes(filter.keyword.trim())))
    .sort((a, b) => a.sort_order - b.sort_order || a.id.localeCompare(b.id))
}
