// @vitest-environment jsdom
import { beforeEach, expect, test } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { http } from '../api'
import { businessGeneration, clearBusinessSession } from '../business/state'
import { useBusinessStore } from './business'
beforeEach(() => { clearBusinessSession(); setActivePinia(createPinia()) })
test.each(['resolve', 'reject'])('old bootstrap %s cannot refill data or finalize a newer load', async outcome => {
  const finishes: Array<() => void> = []
  http.defaults.adapter = config => new Promise((resolve, reject) => {
    const index = finishes.length
    finishes.push(() => outcome === 'reject' && index === 0 ? reject(new Error('old network failure')) : resolve({ config, headers: {}, status: 200, statusText: '', data: { data: { employee: { id: 'e1' }, catalog: [{ id: index ? 'new' : 'old' }], wristbands: [] } } }))
  })
  const store = useBusinessStore()
  const old = store.refreshBootstrap().catch(() => undefined)
  await Promise.resolve(); await Promise.resolve()
  clearBusinessSession()
  const generation = businessGeneration.capture()
  const current = store.refreshBootstrap()
  await Promise.resolve(); await Promise.resolve()
  finishes[0]!(); await old
  expect(businessGeneration.isCurrent(generation)).toBe(true)
  expect(store.loading).toBe(true)
  expect(store.error).toBe('')
  expect(store.catalog).toEqual([])
  finishes[1]!(); await current
  expect(store.catalog[0]?.id).toBe('new')
  expect(store.loading).toBe(false)
})
test('out-of-order bootstrap queries keep the latest catalog', async () => {
  const finishes: Array<() => void> = []
  http.defaults.adapter = config => new Promise(resolve => {
    const id = finishes.length ? 'new' : 'old'
    finishes.push(() => resolve({ config, headers: {}, status: 200, statusText: '', data: { data: { employee: { id: 'e1' }, catalog: [{ id }], wristbands: [] } } }))
  })
  const store = useBusinessStore()
  const old = store.refreshBootstrap(); await Promise.resolve(); await Promise.resolve()
  const latest = store.refreshBootstrap(); await Promise.resolve(); await Promise.resolve()
  finishes[1]!(); await latest
  finishes[0]!(); await old
  expect(store.catalog[0]?.id).toBe('new')
})
test('a newer silent bootstrap completes the loading indicator it supersedes', async () => {
  const finishes: Array<() => void> = []
  http.defaults.adapter = config => new Promise(resolve => finishes.push(() => resolve({ config, headers: {}, status: 200, statusText: '', data: { data: { employee: { id: 'e1' }, catalog: [], wristbands: [] } } })))
  const store = useBusinessStore()
  const old = store.refreshBootstrap(); const latest = store.refreshBootstrap(true)
  finishes[1]!(); await latest
  expect(store.loading).toBe(false)
  finishes[0]!(); await old
  expect(store.loading).toBe(false)
})

test('visit UUID drafts survive switching and a closed UUID cannot transfer to a reused number', async () => {
  const store = useBusinessStore()
  store.selectVisit('a'); store.quantities = { towel: 2 }
  store.selectVisit('b'); store.quantities = { water: 3 }
  store.selectVisit('a'); expect(store.quantities).toEqual({ towel: 2 })
  http.defaults.adapter = async config => ({ config, headers: {}, status: 200, statusText: '', data: { data: {
    employee: { id: 'e1' }, catalog: [], wristbands: [{ number: '001', visit_id: 'new-a' }] } } })
  await store.refreshBootstrap()
  store.selectVisit('new-a'); expect(store.quantities).toEqual({})
  clearBusinessSession(); store.selectVisit('b'); expect(store.quantities).toEqual({})
})

test('uncertain mobile retry retains its original immutable payload and version', () => {
  const store = useBusinessStore()
  const items = [{ catalog_item_id: 'towel', quantity: 2 }]
  const first = store.prepareOrder('a', 3, items)
  items[0]!.quantity = 7
  const retry = store.prepareOrder('a', 9, [{ catalog_item_id: 'towel', quantity: 2 }])
  expect(retry).toEqual(first)
  expect(retry.version).toBe(3)
  expect(retry.items[0]!.quantity).toBe(2)
  expect(() => store.prepareOrder('a', 9, [{ catalog_item_id: 'water', quantity: 1 }])).toThrow('尚未确认')
  store.rejectOrder('a', 409)
  expect(store.prepareOrder('a', 9, [{ catalog_item_id: 'water', quantity: 1 }]).version).toBe(9)
})

test('mobile package replacement confirmation is frozen and part of retry identity', () => {
  const store=useBusinessStore()
  const first=store.prepareOrder('a',3,[{catalog_item_id:'packageB',quantity:1}],true)
  expect(first.confirmReplace).toBe(true)
  expect(store.prepareOrder('a',8,[{catalog_item_id:'packageB',quantity:1}],true)).toEqual(first)
  expect(()=>store.prepareOrder('a',8,[{catalog_item_id:'packageB',quantity:1}],false)).toThrow('尚未确认')
})

test('pending original is isolated from a fresh draft and completing it cannot erase that draft',()=>{
  const store=useBusinessStore();store.selectVisit('a');store.quantities={product:3};store.materials={product:[{stock_item_id:'s',quantity:'1.5'}]}
  store.prepareOrder('a',3,[{catalog_item_id:'product',quantity:'3',inventory_mode:'manual',inventory_consumption:store.materials.product}],true)
  expect(store.quantities).toEqual({});expect(store.materials).toEqual({})
  store.quantities={service:1};store.materials={service:[]}
  store.completeOrder('a')
  expect(store.quantities).toEqual({service:1});expect(store.materials).toEqual({service:[]})
  clearBusinessSession();expect(store.pendingOrder('a')).toBeUndefined();expect(store.materials).toEqual({})
})

test('out-of-order consumable queries preserve the latest stock version',async()=>{
  const finishes:Array<()=>void>=[]
  http.defaults.adapter=config=>new Promise(resolve=>{const version=finishes.length?2:1;finishes.push(()=>resolve({config,headers:{},status:200,statusText:'',data:{data:[{id:'s',name:'奶浴袋',category:'耗材',base_unit:'袋',package_spec:'1*200',stock_quantity:version===1?'800':'799',version}]}}))})
  const store=useBusinessStore();const first=store.loadConsumables();const latest=store.loadConsumables()
  finishes[1]!();await latest;finishes[0]!();await first
  expect(store.consumables[0]?.version).toBe(2);expect(store.consumables[0]?.stock_quantity).toBe('799')
})
