import { expect, it } from 'vitest'
import { togglePackageSelection } from './order-package'
import { visibleCatalog } from './domain/catalog/filter'
it('one selected package replaces another without removing goods or services', () => {
  const catalog = [{id:'A',kind:'package'},{id:'B',kind:'package'},{id:'scrub',kind:'service'},{id:'water',kind:'product'}]
  const original = {A:1,scrub:1,water:3}
  const next = togglePackageSelection(original,catalog,'B')
  expect(next).toEqual({B:1,scrub:1,water:3})
  expect(original).toEqual({A:1,scrub:1,water:3})
  expect(togglePackageSelection(next,catalog,'B')).toEqual({scrub:1,water:3})
})
it('package cards belong to service/all filters, never the goods filter', () => {
  const items = [{id:'A',kind:'package',name:'套票A',category:'套票',sort_order:30},
    {id:'scrub',kind:'service',name:'搓澡',category:'洗浴',sort_order:10},
    {id:'water',kind:'product',name:'水',category:'饮品',sort_order:40}]
  expect(visibleCatalog(items,{kind:'service',category:'',keyword:''}).map(row=>row.id)).toEqual(['scrub','A'])
  expect(visibleCatalog(items,{kind:'all',category:'',keyword:''}).map(row=>row.id)).toEqual(['scrub','A','water'])
  expect(visibleCatalog(items,{kind:'product',category:'',keyword:''}).map(row=>row.id)).toEqual(['water'])
})
