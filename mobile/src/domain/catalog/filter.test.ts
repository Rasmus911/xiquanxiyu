import { expect, it } from 'vitest'
import { visibleCatalog } from './filter'

it('all mixes services and products in global order, excluding tickets and inactive items', () => {
  const items = [
    { id: 'mud', kind: 'product', name: '搓泥宝', category: '洗浴', is_active: true, sort_order: 20 },
    { id: 'scrub', kind: 'service', name: '搓澡', category: '洗浴', is_active: true, sort_order: 10 },
    { id: 'ticket', kind: 'ticket', name: '门票', category: '门票', is_active: true, sort_order: 0 },
    { id: 'old', kind: 'service', name: '旧服务', category: '洗浴', is_active: false, sort_order: 0 },
  ]
  expect(visibleCatalog(items, { kind: 'all', category: '', keyword: '' }).map(row => row.id)).toEqual(['scrub', 'mud'])
  expect(visibleCatalog(items, { kind: 'product', category: '洗浴', keyword: ' 泥 ' }).map(row => row.id)).toEqual(['mud'])
  expect(items[0]!.id).toBe('mud')
})
