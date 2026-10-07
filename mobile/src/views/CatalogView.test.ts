// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest'
import {createApp,h,nextTick} from 'vue'
import {createPinia,setActivePinia} from 'pinia'
import {acceptBusinessState,clearBusinessSession} from '../business/state'
import {http} from '../api'
const views=import.meta.glob('./CatalogView.vue')
let destroy=()=>{}
afterEach(()=>{destroy();clearBusinessSession()})
it('permitted catalog page edits every server-editable kind and shows usage ties',async()=>{
  expect(views['./CatalogView.vue']).toBeDefined()
  const {default:View}=await views['./CatalogView.vue']!() as any
  clearBusinessSession();acceptBusinessState({period_id:'p',policy_version:1,business_revision:1,maintenance:false,owner_reset_allowed:false},['catalog:read','catalog:write'])
  const pinia=createPinia();setActivePinia(pinia);const requests:any[]=[]
  http.defaults.adapter=async config=>{requests.push({url:config.url,method:config.method,body:config.data?JSON.parse(config.data):null});return {config,headers:{},status:200,statusText:'',data:{data:config.url==='/mobile/bootstrap'?{employee:{id:'e'},catalog:[],wristbands:[]}:config.method==='get'?(config.url==='/catalog'?[{id:'a',kind:'service',name:'搓澡',category:'服务',price:'30.00',can_edit:true,is_active:true},{id:'b',kind:'product',name:'锁定商品',category:'商品',price:'5.00',can_edit:false,is_active:true},{id:'p',kind:'package',name:'套票',price:'80.00',can_edit:true,is_active:true}]:[{catalog_item_id:'a',stock_name:'奶浴袋',usage_count:2,is_most_used:true},{catalog_item_id:'a',stock_name:'澡巾',usage_count:2,is_most_used:true}]):{}}}}
  const root=document.createElement('div');document.body.append(root);const app=createApp({render:()=>h(View)});app.use(pinia);app.mount(root);destroy=()=>{app.unmount();root.remove()}
  await vi.waitFor(()=>expect(root.textContent).toContain('奶浴袋'))
  expect(root.textContent).toContain('澡巾');expect(root.querySelector('[data-testid="catalog-edit-b"]')).toBeNull();expect(root.querySelector('[data-testid="catalog-edit-p"]')).not.toBeNull()
  root.querySelector<HTMLButtonElement>('[data-testid="catalog-edit-a"]')!.click();await nextTick()
  const name=root.querySelector<HTMLInputElement>('[name="name"]')!;name.value='奶浴搓澡';name.dispatchEvent(new Event('input'))
  const price=root.querySelector<HTMLInputElement>('[name="price"]')!;price.value='38.50';price.dispatchEvent(new Event('input'));await nextTick()
  root.querySelector<HTMLButtonElement>('[data-testid="catalog-save"]')!.click();await vi.waitFor(()=>expect(requests.some(r=>r.method==='patch')).toBe(true))
  expect(requests.find(r=>r.method==='patch')).toEqual({url:'/catalog/a',method:'patch',body:{name:'奶浴搓澡',category:'服务',price:'38.50',mobile_scope:'both'}})
})

it('a mounted staff catalog page cannot load global catalog/usage or create items',async()=>{
  const {default:View}=await views['./CatalogView.vue']!() as any
  clearBusinessSession();acceptBusinessState({period_id:'p',policy_version:1,business_revision:1,maintenance:false,owner_reset_allowed:false},['mobile:order'])
  let requests=0;http.defaults.adapter=async()=>{requests++;throw new Error('staff cannot call management')}
  const root=document.createElement('div');document.body.append(root);const app=createApp({render:()=>h(View)});app.use(createPinia());app.mount(root);destroy=()=>{app.unmount();root.remove()};await nextTick()
  expect(requests).toBe(0);expect(root.querySelector('[data-testid="catalog-create"]')).toBeNull()
})

it('catalog lists ten items per page with header pagination and resets on search or activity changes',async()=>{
  const {default:View}=await views['./CatalogView.vue']!() as any
  clearBusinessSession();acceptBusinessState({period_id:'p',policy_version:1,business_revision:1,maintenance:false,owner_reset_allowed:false},['catalog:read','catalog:write'])
  http.defaults.adapter=async config=>({config,headers:{},status:200,statusText:'',data:{data:config.url==='/catalog'?Array.from({length:21},(_,i)=>({id:`s${i}`,kind:'service',name:`服务${i}`,category:'服务',price:'1.00',can_edit:i!==10,is_active:config.params?.active!=='false'})):[]}})
  const root=document.createElement('div');document.body.append(root);const app=createApp({render:()=>h(View)});app.use(createPinia());app.mount(root);destroy=()=>{app.unmount();root.remove()}
  await vi.waitFor(()=>expect(root.querySelector('[data-testid="catalog-edit-s0"]')).not.toBeNull())
  expect(root.querySelectorAll('.catalog-row')).toHaveLength(10)
  const pager=root.querySelector('[aria-label="项目分页"]')!;expect(pager.closest('[data-testid="catalog-list"]')).not.toBeNull();expect(pager.parentElement?.classList.contains('list-header')).toBe(true)
  ;([...pager.querySelectorAll('button')].find(b=>b.textContent==='下一页') as HTMLButtonElement).click();await nextTick()
  expect(root.querySelector('[data-testid="catalog-edit-s0"]')).toBeNull();expect(root.querySelector('[data-testid="catalog-edit-s10"]')).toBeNull();expect(root.textContent).toContain('服务10')
  const search=root.querySelector<HTMLInputElement>('input[placeholder="搜索项目"]')!;search.value='服务20';search.dispatchEvent(new Event('input'));await nextTick()
  expect(root.querySelector('[data-testid="catalog-edit-s20"]')).not.toBeNull();expect(pager.textContent).toContain('1 / 1')
  search.value='';search.dispatchEvent(new Event('input'));await nextTick()
  ;([...pager.querySelectorAll('button')].find(b=>b.textContent==='下一页') as HTMLButtonElement).click();await nextTick()
  root.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click();await vi.waitFor(()=>expect(pager.textContent).toContain('1 / 3'))
})
