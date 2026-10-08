import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, expect, it } from 'vitest'
import { http } from '../../api/http'
import { clearBusinessSession } from '../../business/state'
import RegistrationDialog from './RegistrationDialog.vue'
let close=()=>{}
afterEach(()=>{close();clearBusinessSession()})
async function render() {
  const wrapper=mount(RegistrationDialog,{props:{modelValue:true,terminalCode:'XS-test'},global:{plugins:[ElementPlus],stubs:{teleport:true}}});close=()=>wrapper.unmount();await flushPromises()
  for (const [name,value] of Object.entries({username:'13800138000',display_name:'员工',password:'fixture-password',confirmation:'fixture-password',code:'123456'})) await wrapper.find(`[name="${name}"]`).setValue(value)
  return wrapper
}
it('submits real form through HTTP, retains retry key and fields on failure, emits safe username on success',async()=>{
  const requests:any[]=[]
  http.defaults.adapter=async config=>{requests.push({body:JSON.parse(config.data),key:config.headers['Idempotency-Key']});if(requests.length===1)throw new Error('授权码已失效，请向管理员获取新授权码');return {config,status:201,statusText:'',headers:{},data:{data:{id:'e',username:'13800138000',display_name:'员工',role:'male_scrubber',is_active:true,allowed_channels:['desktop']}}}}
  const w=await render();await w.find('[data-testid="registration-submit"]').trigger('click');await flushPromises()
  expect(w.text()).toContain('授权码已失效');expect((w.find('[name="display_name"]').element as HTMLInputElement).value).toBe('员工')
  await w.find('[data-testid="registration-submit"]').trigger('click');await flushPromises()
  expect(requests[0]).toEqual(requests[1]);expect(Object.keys(requests[0].body).sort()).toEqual(['client_channel','code','display_name','password','role','terminal_code','username'])
  expect(requests[0].body).toMatchObject({role:'male_scrubber',client_channel:'desktop'});expect(w.emitted('registered')).toEqual([['13800138000']])
  expect([...Object.values(localStorage),...Object.values(sessionStorage)].join('')).not.toContain('fixture-password')
  expect([...Object.values(localStorage),...Object.values(sessionStorage)].join('')).not.toContain('123456')
})
it('changing submitted data replaces retry identity and unsafe server success stays an error',async()=>{
  const requests:any[]=[];http.defaults.adapter=async config=>{requests.push({body:JSON.parse(config.data),key:config.headers['Idempotency-Key']});return {config,status:201,statusText:'',headers:{},data:{data:{id:'e',username:'13800138000',display_name:'员工',role:'admin',is_active:true,allowed_channels:['desktop'],access_token:'unexpected'}}}}
  const w=await render();await w.find('[data-testid="registration-submit"]').trigger('click');await flushPromises();expect(w.text()).toContain('注册结果无法确认');expect(w.emitted('registered')).toBeUndefined()
  await w.find('[name="code"]').setValue('654321');await w.find('[data-testid="registration-submit"]').trigger('click');await flushPromises();expect(requests[1].key).not.toBe(requests[0].key)
})
it.each(['male_scrubber','female_scrubber','floor_attendant'])('only submits the selected staff role %s',async(role)=>{
  let payload:any
  http.defaults.adapter=async config=>{payload=JSON.parse(config.data);throw new Error('fixture denial')}
  const w=await render();await w.find('select[name="role"]').setValue(role)
  await w.find('[data-testid="registration-submit"]').trigger('click');await flushPromises();expect(payload.role).toBe(role)
  expect(w.findAll('select option').map(option=>option.attributes('value'))).toEqual(['male_scrubber','female_scrubber','floor_attendant'])
  expect([...Object.values(localStorage),...Object.values(sessionStorage)].join('')).not.toContain('fixture-password')
  expect([...Object.values(localStorage),...Object.values(sessionStorage)].join('')).not.toContain('123456')
})
it.each(['close','session','unmount'])('ignores pending success after %s and clears sensitive fields',async(action)=>{
  let resolve!:(value:any)=>void
  http.defaults.adapter=config=>new Promise(r=>{resolve=value=>r({config,status:201,statusText:'',headers:{},data:{data:value}})})
  const w=await render();await w.find('[data-testid="registration-submit"]').trigger('click');await flushPromises()
  if(action==='close')await w.setProps({modelValue:false});else if(action==='session')clearBusinessSession();else w.unmount()
  resolve({id:'e',username:'13800138000',display_name:'员工',role:'male_scrubber',is_active:true,allowed_channels:['desktop']});await flushPromises()
  expect(w.emitted('registered')).toBeUndefined()
  if(action!=='unmount'){await w.setProps({modelValue:true});await flushPromises();expect((w.find('[name="password"]').element as HTMLInputElement).value).toBe('');expect((w.find('[name="code"]').element as HTMLInputElement).value).toBe('')}
})
