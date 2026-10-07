// @vitest-environment jsdom
import { expect, it } from 'vitest'
import { createApp, h, nextTick } from 'vue'
import MobileCatalogPicker from './MobileCatalogPicker.vue'
import { http } from '../../api'

it('service supplies use a one-selection button without product quantity controls',async()=>{
  const root=document.createElement('div');document.body.append(root);const selected:string[]=[]
  const app=createApp({render:()=>h(MobileCatalogPicker,{kind:'all',quantities:{},items:['澡巾','备品','搓泥宝'].map((name,i)=>({id:`s${i}`,kind:'service',name,category:'服务',price:'6',sort_order:i})) as any,onSelect:(item:any)=>selected.push(item.id)})});app.mount(root)
  try{
    await nextTick();expect(root.querySelectorAll('.stepper')).toHaveLength(0)
    for(const row of root.querySelectorAll<HTMLElement>('[data-catalog-id]'))row.click()
    expect(selected).toEqual(['s0','s1','s2'])
  }finally{app.unmount();root.remove()}
})

it('mixed mode shows global order and a stepper click does not also sell another unit', async () => {
  const root = document.createElement('div'); document.body.append(root)
  const selected: string[] = []; const changes: number[] = []
  const app = createApp({ render: () => h(MobileCatalogPicker, { kind: 'all', quantities: {}, items: [
    { id: 'p', kind: 'product', name: '澡巾', category: '洗浴', sort_order: 20, price: '6', stock_tracked: true, stock_quantity: '10' },
    { id: 's', kind: 'service', name: '搓澡', category: '洗浴', sort_order: 10, price: '10' },
    { id: 'zero', kind: 'product', name: '备品', category: '洗浴', sort_order: 30, price: '7', stock_tracked: true, stock_quantity: '0' },
  ] as any, onSelect: (item: any) => selected.push(item.id), onChange: (_: any, delta: number) => changes.push(delta) } as any) })
  app.mount(root)
  try {
    await nextTick()
    expect([...root.querySelectorAll('article > div:first-child > strong')].map(node => node.textContent)).toEqual(['搓澡', '澡巾', '备品'])
    const articles = root.querySelectorAll('article')
    ;(articles[1]!.querySelector('.stepper button:last-child') as HTMLButtonElement).click()
    expect(changes).toEqual([1]); expect(selected).toEqual([])
    ;(articles[2] as HTMLElement).click(); expect(selected).toEqual(['zero'])
  } finally { app.unmount(); root.remove() }
})

it('touch handle rearranges without ordering, stock-zero participates, and saves the complete order once', async () => {
  const root = document.createElement('div'); document.body.append(root)
  const writes: any[] = []; const selected: string[] = []
  http.defaults.adapter = async config => {
    if (config.method === 'put') writes.push(JSON.parse(config.data))
    return { config, headers: {}, status: 200, statusText: '', data: { data: { revision: 2,
      ids: config.method === 'put' ? JSON.parse(config.data).ids : ['s', 'p', 'zero'] } } }
  }
  const app = createApp({ render: () => h(MobileCatalogPicker, { kind: 'all', quantities: { s: 1 }, canArrange: true, items: [
    { id: 's', kind: 'service', name: '搓澡', category: '洗浴', sort_order: 10, price: '10' },
    { id: 'p', kind: 'product', name: '澡巾', category: '洗浴', sort_order: 20, price: '6' },
    { id: 'zero', kind: 'product', name: '备品', category: '洗浴', sort_order: 30, price: '7', stock_tracked: true, stock_quantity: '0' },
  ] as any, onSelect: (item: any) => selected.push(item.id) } as any) })
  app.mount(root)
  const previous = document.elementFromPoint
  try {
    ;(root.querySelector('[data-testid="arrange-start"]') as HTMLButtonElement).click()
    await new Promise(resolve => setTimeout(resolve, 0)); await nextTick()
    const handle = root.querySelector('[aria-label="拖动备品"]')!
    document.elementFromPoint = () => root.querySelector('[data-catalog-id="p"]')!
    for (const type of ['pointerdown', 'pointerup']) {
      const event = new MouseEvent(type, { bubbles: true, button: 0 })
      Object.defineProperties(event, { pointerId: { value: 3 }, pointerType: { value: 'touch' } })
      handle.dispatchEvent(event)
    }
    ;(handle as HTMLButtonElement).click(); await nextTick()
    expect(selected).toEqual([])
    expect([...root.querySelectorAll('[data-catalog-id]')].map(node => node.getAttribute('data-catalog-id'))).toEqual(['s', 'zero', 'p'])
    ;(root.querySelector('[data-testid="arrange-save"]') as HTMLButtonElement).click()
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(writes).toEqual([{ revision: 2, ids: ['s', 'zero', 'p'] }])
  } finally { document.elementFromPoint = previous; app.unmount(); root.remove() }
})
