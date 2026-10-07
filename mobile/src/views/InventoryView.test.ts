// @vitest-environment jsdom
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {createApp,h,nextTick} from 'vue'
import {createPinia,setActivePinia} from 'pinia'
import {acceptBusinessState,clearBusinessSession} from '../business/state'
import {http} from '../api'
import {useSessionStore} from '../stores/session'
import {useBusinessStore} from '../stores/business'
import InventoryView from './InventoryView.vue'
import type {StockItem} from '../types'
const stock:StockItem={id:'s',name:'奶浴袋',category:'耗材',base_unit:'袋',package_unit:'箱',units_per_package:'200.000',package_spec:'1*200',stock_quantity:'800.000',low_stock_threshold:'20.000',is_active:true,version:3}
let destroy=()=>{};let requests:any[]=[]
beforeEach(()=>{clearBusinessSession();requests=[];vi.spyOn(window,'confirm').mockReturnValue(true)})
afterEach(()=>{destroy();clearBusinessSession();vi.restoreAllMocks()})
async function render(allowed=true,master=stock,receiptCost:{id:string;unit_cost:string;total_cost:string;base_unit_cost:string}|null=null){
  acceptBusinessState({period_id:'p',policy_version:1,business_revision:1,maintenance:false,owner_reset_allowed:false},allowed?['inventory:read','inventory:write']:['mobile:order'])
  const pinia=createPinia();setActivePinia(pinia)
  useSessionStore().setEmployee({id:'e',username:'operator',display_name:'员工',role:'inventory',role_label:'库管',capabilities:{inventory_manage:allowed}})
  http.defaults.adapter=async config=>{requests.push({method:config.method,url:config.url,body:config.data?JSON.parse(config.data):undefined,key:config.headers['Idempotency-Key']});return {config,headers:{},status:200,statusText:'',data:{data:config.method==='get'?(config.url==='/inventory/stock-items'?[master]:config.url==='/inventory/stock-movements'?[{id:'m',stock_item_id:'s',movement_type:'opening',quantity:'800.000',input_quantity:'4.000',input_unit:'package',conversion_factor:'200.000',base_unit:'袋',package_unit:'箱',reason:'期初库存',cost:receiptCost}]:[]):{}}}}
  const root=document.createElement('div');document.body.append(root);const app=createApp({render:()=>h(InventoryView)});app.use(pinia);app.mount(root);destroy=()=>{app.unmount();root.remove()};await nextTick();return root
}
async function input(root:HTMLElement,name:string,value:string){const node=root.querySelector<HTMLInputElement>(`[name="${name}"]`)!;expect(node).not.toBeNull();node.value=value;node.dispatchEvent(new Event('input'));await nextTick()}
it('creates an independent master with zero opening omitted, edits packaging, receives packages and confirms writeoff',async()=>{
  const root=await render();await vi.waitFor(()=>expect(root.textContent).toContain('奶浴袋'))
  await vi.waitFor(()=>expect(root.querySelector('details')?.textContent).toContain('4.000 箱 × 200.000'))
  root.querySelector<HTMLButtonElement>('[data-testid="stock-create"]')!.click();await nextTick()
  expect(root.querySelector('[name="category"]')).toBeNull()
  expect(root.querySelector('[name="package_spec"]')).toBeNull()
  await input(root,'name','独立耗材');await input(root,'base_unit','袋');await input(root,'package_unit','箱');await input(root,'units_per_package','200');await input(root,'opening_quantity','0')
  root.querySelector<HTMLButtonElement>('[data-testid="stock-save"]')!.click()
  await vi.waitFor(()=>expect(requests.some(r=>r.method==='post')).toBe(true))
  const create=requests.find(r=>r.method==='post');expect(create.url).toBe('/inventory/stock-items');expect(create.body.name).toBe('独立耗材');expect(create.body).not.toHaveProperty('opening_quantity');expect(create.key).toBeTruthy()
  await vi.waitFor(()=>expect(root.querySelector('[data-testid="stock-save"]')).toBeNull())
  root.querySelector<HTMLButtonElement>('[data-testid="stock-edit-s"]')!.click();await nextTick();await input(root,'units_per_package','250')
  expect(root.querySelector<HTMLInputElement>('[name="base_unit"]')!.disabled).toBe(true)
  root.querySelector<HTMLButtonElement>('[data-testid="stock-save"]')!.click();await vi.waitFor(()=>expect(requests.some(r=>r.method==='patch')).toBe(true))
  expect(requests.find(r=>r.method==='patch').body).toMatchObject({version:3,units_per_package:'250'});expect(requests.find(r=>r.method==='patch').body).not.toHaveProperty('base_unit')
  await vi.waitFor(()=>expect(root.querySelector('[data-testid="stock-save"]')).toBeNull())
  root.querySelector<HTMLButtonElement>('[data-testid="stock-receive-s"]')!.click();await nextTick()
  const quantity=root.querySelector<HTMLInputElement>('.sheet input')!;quantity.value='4';quantity.dispatchEvent(new Event('input'))
  const unit=root.querySelector<HTMLSelectElement>('.sheet select')!;unit.value='package';unit.dispatchEvent(new Event('change'));await nextTick()
  await input(root,'unit_cost','120')
  expect(root.querySelector('.sheet')!.textContent).toContain('480.00')
  expect(root.querySelector('.sheet')!.textContent).toContain('800.000 袋');root.querySelector<HTMLButtonElement>('.sheet .primary-button')!.click()
  await vi.waitFor(()=>expect(requests.some(r=>r.url==='/inventory/stock-adjust')).toBe(true))
  expect(requests.find(r=>r.url==='/inventory/stock-adjust').body).toMatchObject({stock_item_id:'s',version:3,movement_type:'purchase',quantity:'4',input_unit:'package',unit_cost:'120'})
  await vi.waitFor(()=>expect(root.querySelector('.sheet')).toBeNull())
  vi.mocked(window.confirm).mockReturnValue(false);root.querySelector<HTMLButtonElement>('[data-testid="stock-delete-s"]')!.click();await nextTick();expect(requests.some(r=>r.method==='delete')).toBe(false)
  vi.mocked(window.confirm).mockReturnValue(true);root.querySelector<HTMLButtonElement>('[data-testid="stock-delete-s"]')!.click();await vi.waitFor(()=>expect(requests.some(r=>r.method==='delete')).toBe(true))
  expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('800.000 袋'))
  expect(requests.find(r=>r.method==='delete').body).toEqual({version:3,confirm_writeoff:true})
})
it('mounted staff page cannot load or mutate global stock',async()=>{
  const root=await render(false);await nextTick();expect(requests).toHaveLength(0);expect(root.querySelector('[data-testid="stock-create"]')).toBeNull()
})

it.each([null,'0.00','2.50'])('edits master cost %s with first assignment and own-password protection independent of receipt history',async(currentCost)=>{
  const root=await render(true,{...stock,unit_cost:currentCost} as StockItem)
  await vi.waitFor(()=>expect(root.querySelector('[data-testid="stock-edit-s"]')).not.toBeNull())
  expect(root.querySelector('[data-testid="stock-cost-s"]')?.textContent).toContain(currentCost===null?'未设置':currentCost)
  root.querySelector<HTMLButtonElement>('[data-testid="stock-edit-s"]')!.click();await nextTick()
  await input(root,'master_unit_cost','3.00')
  const save=root.querySelector<HTMLButtonElement>('[data-testid="stock-save"]')!
  if(currentCost!==null){
    expect(save.disabled).toBe(true);save.dispatchEvent(new MouseEvent('click'));await nextTick()
    expect(requests.some(r=>r.method==='patch')).toBe(false)
    await input(root,'password','my-own-password')
  }else expect(root.querySelector('[name="password"]')).toBeNull()
  save.click();await vi.waitFor(()=>expect(requests.some(r=>r.method==='patch')).toBe(true))
  expect(requests.find(r=>r.method==='patch').body).toEqual({name:'奶浴袋',package_unit:'箱',units_per_package:'200.000',version:3,unit_cost:'3.00',...(currentCost===null?{}:{password:'my-own-password'})})
  expect(requests.filter(r=>r.method!=='get').map(r=>r.url)).toEqual(['/inventory/stock-items/s'])
})

it('unchanged normalized master cost does not request a password, invalid or cleared assigned cost cannot submit',async()=>{
  const root=await render(true,{...stock,unit_cost:'0.00'} as StockItem)
  await vi.waitFor(()=>expect(root.querySelector('[data-testid="stock-edit-s"]')).not.toBeNull())
  root.querySelector<HTMLButtonElement>('[data-testid="stock-edit-s"]')!.click();await nextTick()
  for(const value of ['','-1','1.001','10000000000','NaN']){
    await input(root,'master_unit_cost',value);expect(root.querySelector<HTMLButtonElement>('[data-testid="stock-save"]')!.disabled).toBe(true)
  }
  await input(root,'master_unit_cost','0');expect(root.querySelector('[name="password"]')).toBeNull()
  root.querySelector<HTMLButtonElement>('[data-testid="stock-save"]')!.click()
  await vi.waitFor(()=>expect(requests.some(r=>r.method==='patch')).toBe(true))
  expect(requests.find(r=>r.method==='patch').body).not.toHaveProperty('password')
})

it('an uncertain cost change keeps retry identity without persisting the login password',async()=>{
  const root=await render(true,{...stock,unit_cost:'1.00'} as StockItem)
  await vi.waitFor(()=>expect(root.querySelector('[data-testid="stock-edit-s"]')).not.toBeNull())
  root.querySelector<HTMLButtonElement>('[data-testid="stock-edit-s"]')!.click();await nextTick()
  await input(root,'master_unit_cost','2.00');await input(root,'password','fixture-secret-password')
  const writes:any[]=[]
  http.defaults.adapter=async config=>{writes.push({body:JSON.parse(config.data),key:config.headers['Idempotency-Key']});throw new Error('uncertain network')}
  root.querySelector<HTMLButtonElement>('[data-testid="stock-save"]')!.click()
  await vi.waitFor(()=>expect(root.textContent).toContain('uncertain network'))
  const stored=Object.keys(localStorage).map(key=>localStorage.getItem(key)).join('')
  expect(stored).not.toContain('fixture-secret-password')
  root.querySelector<HTMLButtonElement>('[data-testid="stock-save"]')!.click()
  await vi.waitFor(()=>expect(writes).toHaveLength(2));expect(writes[1]).toEqual(writes[0]);expect(writes[0].body.password).toBe('fixture-secret-password')
})

it.each([null,'0.00','120.00'])('receipt cost %s can be first recorded freely but a changed assigned cost needs the current login password',async(prior)=>{
  const root=await render(true,stock,prior===null?null:{id:'prior',unit_cost:prior,total_cost:prior==='0.00'?'0.00':'480.00',base_unit_cost:prior==='0.00'?'0.000000':'0.600000'})
  await vi.waitFor(()=>expect(root.querySelector('details button')).not.toBeNull())
  root.querySelector<HTMLButtonElement>('details button')!.click();await nextTick()
  const field=root.querySelector<HTMLInputElement>('.sheet input')!;field.value='130';field.dispatchEvent(new Event('input'));await nextTick()
  const save=[...root.querySelectorAll<HTMLButtonElement>('.sheet button')].find(node=>node.textContent==='保存成本')!
  if(prior!==null){
    expect(save.disabled).toBe(true);save.dispatchEvent(new MouseEvent('click'));await nextTick()
    expect(requests.filter(row=>row.method!=='get')).toEqual([])
    await input(root,'receipt_password','current-login-password')
    expect(save.disabled).toBe(false)
  }else expect(root.querySelector('input[type="password"]')).toBeNull()
  save.click();await vi.waitFor(()=>expect(requests.some(row=>row.url==='/inventory/stock-movements/m/cost')).toBe(true))
  const write=requests.find(row=>row.url==='/inventory/stock-movements/m/cost')
  expect(write.method).toBe('post');expect(write.body).toEqual({unit_cost:'130',expected_cost_id:prior===null?null:'prior',...(prior===null?{}:{password:'current-login-password'})})
  expect(requests.some(row=>row.url==='/inventory/stock-adjust'||(row.method==='patch'&&row.url==='/inventory/stock-items/s'))).toBe(false)
})

it('the same receipt cost normalizes decimals without a password and rejects invalid price input',async()=>{
  const root=await render(true,stock,{id:'prior',unit_cost:'0.00',total_cost:'0.00',base_unit_cost:'0.000000'})
  await vi.waitFor(()=>expect(root.querySelector('details button')).not.toBeNull())
  root.querySelector<HTMLButtonElement>('details button')!.click();await nextTick()
  const field=root.querySelector<HTMLInputElement>('.sheet input')!
  const save=[...root.querySelectorAll<HTMLButtonElement>('.sheet button')].find(node=>node.textContent==='保存成本')!
  for(const value of ['','-1','1.001','10000000000']){field.value=value;field.dispatchEvent(new Event('input'));await nextTick();expect(save.disabled).toBe(true)}
  field.value='0';field.dispatchEvent(new Event('input'));await nextTick()
  expect(root.querySelector('input[type="password"]')).toBeNull();expect(save.disabled).toBe(false)
  save.click();await vi.waitFor(()=>expect(requests.some(row=>row.url==='/inventory/stock-movements/m/cost')).toBe(true))
  expect(requests.find(row=>row.url==='/inventory/stock-movements/m/cost').body).toEqual({unit_cost:'0',expected_cost_id:'prior'})
})

it('receipt amendment retries preserve the original expected cost while keeping its login password out of storage',async()=>{
  const root=await render(true,stock,{id:'prior',unit_cost:'0.00',total_cost:'0.00',base_unit_cost:'0.000000'})
  await vi.waitFor(()=>expect(root.querySelector('details button')).not.toBeNull())
  root.querySelector<HTMLButtonElement>('details button')!.click();await nextTick()
  const field=root.querySelector<HTMLInputElement>('.sheet input')!;field.value='1';field.dispatchEvent(new Event('input'));await nextTick()
  await input(root,'receipt_password','receipt-fixture-secret')
  const writes:any[]=[];http.defaults.adapter=async config=>{writes.push({body:JSON.parse(config.data),key:config.headers['Idempotency-Key']});throw new Error('receipt uncertainty')}
  const save=[...root.querySelectorAll<HTMLButtonElement>('.sheet button')].find(node=>node.textContent==='保存成本')!
  save.click();await vi.waitFor(()=>expect(root.textContent).toContain('receipt uncertainty'))
  expect(Object.keys(localStorage).map(key=>localStorage.getItem(key)).join('')).not.toContain('receipt-fixture-secret')
  save.click();await vi.waitFor(()=>expect(writes).toHaveLength(2));expect(writes[1]).toEqual(writes[0])
  expect(writes[0].body).toEqual({unit_cost:'1',expected_cost_id:'prior',password:'receipt-fixture-secret'})
})

it('stock list pages ten items from the list header and search resets its page',async()=>{
  const root=await render();await vi.waitFor(()=>expect(root.querySelector('[data-testid="stock-edit-s"]')).not.toBeNull())
  useBusinessStore().inventory=Array.from({length:21},(_,i)=>({...stock,id:`s${i}`,name:`耗材${i}`}));await nextTick()
  expect(root.querySelectorAll('[data-testid^="stock-edit-"]')).toHaveLength(10)
  const pager=root.querySelector('[aria-label="库存分页"]')!;expect(pager.closest('[data-testid="inventory-list"]')).not.toBeNull()
  expect(pager.parentElement?.classList.contains('list-header')).toBe(true)
  ;([...pager.querySelectorAll('button')].find(b=>b.textContent==='下一页') as HTMLButtonElement).click();await nextTick()
  expect(root.querySelector('[data-testid="stock-edit-s10"]')).not.toBeNull();expect(root.querySelector('[data-testid="stock-edit-s0"]')).toBeNull()
  const search=root.querySelector<HTMLInputElement>('input[placeholder="搜索库存"]')!;search.value='耗材20';search.dispatchEvent(new Event('input'));await nextTick()
  expect(root.querySelector('[data-testid="stock-edit-s20"]')).not.toBeNull();expect(pager.textContent).toContain('1 / 1')
})

it.each([['1.001','1.001'],['500000000','2'],['1000000000','1'],['1','1000000000'],['-1','1'],['NaN','1'],['Infinity','1']])('blocks opening %s × %s before HTTP/idempotency and accepts corrected exact input',async(quantity,factor)=>{
  const root=await render();root.querySelector<HTMLButtonElement>('[data-testid="stock-create"]')!.click();await nextTick()
  await input(root,'name','独立耗材');await input(root,'base_unit','袋');await input(root,'package_unit','箱');await input(root,'units_per_package',factor);await input(root,'opening_quantity',quantity)
  const unit=root.querySelector<HTMLSelectElement>('.sheet select')!;unit.value='package';unit.dispatchEvent(new Event('change'));await nextTick()
  const button=root.querySelector<HTMLButtonElement>('[data-testid="stock-save"]')!
  expect(button.disabled).toBe(true);expect(root.querySelector('[role="alert"]')?.textContent).toBeTruthy()
  button.click();button.dispatchEvent(new MouseEvent('click',{bubbles:true}));await nextTick()
  expect(requests.filter(row=>row.method!=='get')).toEqual([])
  expect(Object.keys(localStorage).filter(key=>key.startsWith('xiquan_mobile_pending_operation_stock:'))).toEqual([])
  await input(root,'units_per_package','1.001');await input(root,'opening_quantity','2')
  expect(root.querySelector('.sheet')!.textContent).not.toContain('修改包装规格')
  expect(button.disabled).toBe(false);expect(root.querySelector('.sheet')!.textContent).toContain('2.002 袋');button.click()
  await vi.waitFor(()=>expect(requests.some(row=>row.method==='post')).toBe(true))
  expect(requests.find(row=>row.method==='post').body).toMatchObject({opening_quantity:'2',opening_unit:'package',units_per_package:'1.001'})
})

it.each([['1.001','1.001','2.002'],['500000000','2','4.000']])('receipt %s × %s creates no HTTP/key until an exact correction',async(quantity,factor,corrected)=>{
  const root=await render(true,{...stock,units_per_package:factor});await vi.waitFor(()=>expect(root.querySelector('[data-testid="stock-receive-s"]')).not.toBeNull())
  root.querySelector<HTMLButtonElement>('[data-testid="stock-receive-s"]')!.click();await nextTick()
  const field=root.querySelector<HTMLInputElement>('.sheet input')!;field.value=quantity;field.dispatchEvent(new Event('input'))
  const unit=root.querySelector<HTMLSelectElement>('.sheet select')!;unit.value='package';unit.dispatchEvent(new Event('change'));await nextTick()
  const button=root.querySelector<HTMLButtonElement>('.sheet .primary-button')!;expect(button.disabled).toBe(true);button.dispatchEvent(new MouseEvent('click',{bubbles:true}));await nextTick()
  expect(requests.filter(row=>row.method!=='get')).toEqual([]);expect(Object.keys(localStorage).filter(key=>key.startsWith('xiquan_mobile_pending_operation_stock:'))).toEqual([])
  field.value='2';field.dispatchEvent(new Event('input'));await nextTick();expect(button.disabled).toBe(false);expect(root.querySelector('.sheet')!.textContent).toContain(`${corrected} 袋`);button.click()
  await vi.waitFor(()=>expect(requests.some(row=>row.method==='post')).toBe(true))
  expect(requests.find(row=>row.method==='post')).toMatchObject({url:'/inventory/stock-adjust',body:{stock_item_id:'s',version:3,quantity:'2',input_unit:'package'}})
})
