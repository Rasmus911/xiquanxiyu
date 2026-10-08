// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { createApp, h, nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import { http } from '../api'
import { clearBusinessSession } from '../business/state'
import { useSessionStore } from '../stores/session'
import RegistrationTokenView from './RegistrationTokenView.vue'
import ProfileView from './ProfileView.vue'
const native = vi.hoisted(() => ({ enabled: false, callback: null as null | ((value:{isActive:boolean})=>void), remove: vi.fn(), getState: vi.fn() }))
vi.mock('@capacitor/core',()=>({Capacitor:{isNativePlatform:()=>native.enabled}}))
vi.mock('@capacitor/app',()=>({App:{addListener:async (_event:string,callback:(value:{isActive:boolean})=>void)=>{native.callback=callback;return {remove:native.remove}},getState:native.getState}}))
let destroy=()=>{}
afterEach(()=>{destroy();clearBusinessSession();vi.restoreAllMocks();vi.useRealTimers();native.enabled=false;native.callback=null;vi.clearAllMocks()})
async function render(allowed=true, view=RegistrationTokenView){
  const pinia=createPinia();setActivePinia(pinia);const session=useSessionStore();session.authenticated=true;session.setEmployee({id:'e',username:'18603346509',display_name:'管理员',role:'admin',role_label:'管理员',capabilities:{registration_token_view:allowed}})
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/',component:RegistrationTokenView},{path:'/profile',component:{template:'<p>我的</p>'}}]});await router.push('/');await router.isReady()
  const root=document.createElement('div');document.body.append(root);const app=createApp({render:()=>h(view)});app.use(pinia);app.use(router);app.mount(root);destroy=()=>{app.unmount();root.remove()};await nextTick();return {root,session,router}
}
const snapshot={code:'123456',generation:1,server_time:'2026-10-08T00:00:00Z',expires_at:'2026-10-08T00:03:00Z'}
it('queries only when authorized, clears immediately offline and freshly queries on return',async()=>{
  const calls:any[]=[];http.defaults.adapter=async config=>{calls.push(config);return {config,status:200,statusText:'',headers:{},data:{data:snapshot}}}
  const {root}=await render();await vi.waitFor(()=>expect(root.textContent).toContain('123456'));expect(calls[0].url).toBe('/auth/registration-token/current');expect(calls[0].method).toBe('post');expect(calls[0].data).toBe('{}')
  window.dispatchEvent(new Event('offline'));await nextTick();expect(root.textContent).not.toContain('123456');expect(root.textContent).toContain('网络')
  window.dispatchEvent(new Event('online'));await vi.waitFor(()=>expect(calls).toHaveLength(2));await vi.waitFor(()=>expect(root.textContent).toContain('123456'))
  expect(Object.values(localStorage).join('')).not.toContain('123456');expect(Object.values(sessionStorage).join('')).not.toContain('123456')
})
it.each(['logout','background','account','leave'])('obsolete response never restores token after %s',async(action)=>{
  let resolve!:(value:any)=>void;http.defaults.adapter=config=>new Promise(r=>{resolve=value=>r({config,status:200,statusText:'',headers:{},data:{data:value}})})
  const {root,session,router}=await render();await vi.waitFor(()=>expect(resolve).toBeTypeOf('function'))
  if(action==='logout')clearBusinessSession();else if(action==='account')session.setEmployee({...session.employee!,id:'other'});else if(action==='leave')await router.push('/profile');else{vi.spyOn(document,'visibilityState','get').mockReturnValue('hidden');document.dispatchEvent(new Event('visibilitychange'))}
  resolve(snapshot);await nextTick();await Promise.resolve();await nextTick();expect(root.textContent).not.toContain('123456')
})
it('forbidden capability makes no request',async()=>{let count=0;http.defaults.adapter=async()=>{count++;throw new Error('unexpected')};const {root}=await render(false);await nextTick();expect(count).toBe(0);expect(root.textContent).toContain('无权')})

it('polls at five seconds with one in-flight query, clears failure and expires using monotonic time',async()=>{
  let clock=0;vi.spyOn(performance,'now').mockImplementation(()=>clock);vi.useFakeTimers()
  let count=0,finish!:(value:any)=>void
  http.defaults.adapter=config=>{count++;if(count===1)return Promise.resolve({config,status:200,statusText:'',headers:{},data:{data:{...snapshot,expires_at:'2026-10-08T00:00:03Z'}}});return new Promise((_r,reject)=>{finish=reject})}
  const {root}=await render();await Promise.resolve();await Promise.resolve();await nextTick();expect(root.textContent).toContain('123456')
  clock=3000;await vi.advanceTimersByTimeAsync(3000);expect(root.textContent).not.toContain('123456');expect(root.textContent).toContain('过期');expect(count).toBe(1)
  clock=5000;await vi.advanceTimersByTimeAsync(2000);expect(count).toBe(2)
  clock=15000;await vi.advanceTimersByTimeAsync(10000);expect(count).toBe(2)
  finish(new Error('network failed'));await vi.advanceTimersByTimeAsync(0);await nextTick();expect(root.textContent).not.toContain('123456');expect(root.textContent).toContain('network failed')
})
it('native background event wins over a delayed initial state and removes its listener',async()=>{
  native.enabled=true;let initial!:(value:{isActive:boolean})=>void;native.getState.mockImplementation(()=>new Promise(resolve=>{initial=resolve}));native.remove.mockResolvedValue(undefined)
  let count=0;http.defaults.adapter=async config=>{count++;return {config,status:200,statusText:'',headers:{},data:{data:snapshot}}}
  const {root}=await render();await vi.waitFor(()=>expect(initial).toBeTypeOf('function'));native.callback!({isActive:false});initial({isActive:true});await Promise.resolve();await nextTick()
  expect(count).toBe(0);expect(root.textContent).not.toContain('123456')
  native.callback!({isActive:true});await vi.waitFor(()=>expect(root.textContent).toContain('123456'))
  native.callback!({isActive:false});await nextTick();expect(root.textContent).not.toContain('123456')
  destroy();expect(native.remove).toHaveBeenCalledTimes(1);destroy=()=>{}
})
it('an ordinary bootstrap refresh for the same authorized employee preserves a usable snapshot',async()=>{
  http.defaults.adapter=async config=>({config,status:200,statusText:'',headers:{},data:{data:snapshot}})
  const {root,session}=await render();await vi.waitFor(()=>expect(root.textContent).toContain('123456'))
  session.setEmployee({...session.employee!,display_name:'管理员更新'});await nextTick();expect(root.textContent).toContain('123456')
})
it.each([false,true])('profile registration entry follows only explicit server capability %s',async(allowed)=>{
  const {root}=await render(allowed,ProfileView);await nextTick()
  expect([...root.querySelectorAll('button')].some(button=>button.textContent==='查看注册授权码')).toBe(allowed)
})
it('a failed current query clears a previously usable token immediately',async()=>{
  let count=0;http.defaults.adapter=async config=>{count++;if(count>1)throw new Error('云端请求失败');return {config,status:200,statusText:'',headers:{},data:{data:snapshot}}}
  const {root}=await render();await vi.waitFor(()=>expect(root.textContent).toContain('123456'));root.querySelector<HTMLButtonElement>('.outline-button')!.click()
  await vi.waitFor(()=>expect(root.textContent).toContain('云端请求失败'));expect(root.textContent).not.toContain('123456')
})
