import { afterEach, beforeEach, expect, it } from 'vitest'
import { effectScope } from 'vue'
import { http } from '../api/http'
import { clearBusinessSession } from '../business/state'
import { useVisitOrdering } from './useVisitOrdering'

const scope = effectScope()
beforeEach(() => clearBusinessSession())
afterEach(() => clearBusinessSession())

it('out of order detail requests cannot overwrite the current selection', async () => {
  const finish = new Map<string, () => void>()
  http.defaults.adapter = config => new Promise(resolve => finish.set(String(config.url), () => resolve({
    config, headers: {}, status: 200, statusText: '', data: { data: { id: String(config.url).split('/').at(-1), version: 1 } },
  })))
  const ordering = scope.run(() => useVisitOrdering())!
  const a = ordering.load('a'); const b = ordering.load('b'); const c = ordering.load('c')
  finish.get('/visits/c')!(); await c
  finish.get('/visits/b')!(); await b
  finish.get('/visits/a')!(); await a
  expect(ordering.currentVisit.value?.id).toBe('c')
  expect(ordering.loading.value).toBe(false)
})
it('uncertain retries preserve the original version, UUID, quantities and key', async () => {
  const requests: any[] = []; let fail = true
  http.defaults.adapter = async config => {
    requests.push({ url: config.url, body: JSON.parse(config.data), key: config.headers['Idempotency-Key'] })
    if (fail) throw new Error('network unavailable')
    return { config, headers: {}, status: 201, statusText: '', data: { data: [] } }
  }
  const ordering = scope.run(() => useVisitOrdering())!
  ordering.drafts.replace('a', { soap: 2 })
  await expect(ordering.submitSnapshot(ordering.drafts.capture('a', 3))).rejects.toThrow()
  ordering.drafts.replace('b', { water: 4 })
  fail = false
  await ordering.submitSnapshot(ordering.drafts.capture('a', 8))
  expect(requests[1]).toEqual(requests[0])
  expect(requests[1].body.version).toBe(3)
  expect(ordering.drafts.read('b')).toEqual({ water: 4 })
})
it('old submission success does not clear a new session draft', async () => {
  let finish!: () => void
  http.defaults.adapter = config => new Promise(resolve => { finish = () => resolve({ config,
    headers: {}, status: 201, statusText: '', data: { data: [] } }) })
  const ordering = scope.run(() => useVisitOrdering())!
  ordering.drafts.replace('a', { soap: 2 })
  const pending = ordering.submitSnapshot(ordering.drafts.capture('a', 1)).catch(() => undefined)
  clearBusinessSession(); ordering.drafts.replace('a', { water: 5 })
  finish(); await pending
  expect(ordering.drafts.read('a')).toEqual({ water: 5 })
})

it('uncertain package replacement retains the confirmed immutable payload', async () => {
  const requests: any[]=[]; let fail=true
  http.defaults.adapter=async config=>{
    requests.push({url:config.url,body:JSON.parse(config.data),key:config.headers['Idempotency-Key']})
    if(fail) throw new Error('lost reply')
    return {config,headers:{},status:201,statusText:'',data:{data:[]}}
  }
  const ordering=scope.run(()=>useVisitOrdering())!
  ordering.drafts.replace('a',{packageB:1,water:2})
  const target=Object.freeze({...ordering.drafts.capture('a',3),confirmReplace:true})
  await expect(ordering.submitSnapshot(target)).rejects.toThrow()
  fail=false
  await ordering.submitSnapshot({...target,visitVersion:8})
  expect(requests[1]).toEqual(requests[0])
  expect(requests[0].body.confirm_replace).toBe(true)
  expect(requests[0].body).not.toHaveProperty('price')
})

it('manual stock retry retains the TOTAL quantities, empty manual state and original key after a lost reply',async()=>{
 const requests:any[]=[];let fail=true
 http.defaults.adapter=async config=>{
  requests.push({body:JSON.parse(config.data),key:config.headers['Idempotency-Key']})
  if(fail)throw new Error('lost reply')
  return {config,headers:{},status:201,statusText:'',data:{data:[]}}
 }
 const ordering=scope.run(()=>useVisitOrdering())!
 ordering.drafts.replace('a',{soap:2,service:1})
 const target={...ordering.drafts.capture('a',3),consumptions:{soap:[{stock_item_id:'s1',quantity:'1'}],service:[]}}
 await expect(ordering.submitSnapshot(target)).rejects.toThrow()
 await expect(ordering.submitSnapshot({...target,consumptions:{soap:[{stock_item_id:'s1',quantity:'2'}],service:[]}})).rejects.toThrow('上一笔加单尚未确认')
 fail=false;await ordering.submitSnapshot({...target,visitVersion:9})
 expect(requests[1]).toEqual(requests[0])
 expect(requests[0].body.items).toEqual([{catalog_item_id:'soap',quantity:2,inventory_mode:'manual',inventory_consumption:[{stock_item_id:'s1',quantity:'1'}]},{catalog_item_id:'service',quantity:1,inventory_mode:'manual',inventory_consumption:[]}])
})

it('retryPending restores an immutable original request across composable instances and clears definite rejection',async()=>{
  const requests:any[]=[];let rejection:unknown=new Error('reply lost')
  http.defaults.adapter=async config=>{
    requests.push({raw:config.data,key:config.headers['Idempotency-Key']})
    if(rejection)throw rejection
    return {config,headers:{},status:201,statusText:'',data:{data:[]}}
  }
  const first=scope.run(()=>useVisitOrdering())!
  const target={visitId:'a',visitVersion:3,quantities:{packageB:1},units:1,kinds:1,confirmReplace:true,consumptions:{packageB:[{stock_item_id:'s1',quantity:'0.125'}]}}
  await expect(first.submitSnapshot(target)).rejects.toThrow('reply lost')
  target.visitVersion=9;target.confirmReplace=false;target.consumptions.packageB[0]!.quantity='2'
  const next=scope.run(()=>useVisitOrdering())!
  expect(next.pendingTarget('a')?.visitVersion).toBe(3)
  rejection={response:{status:409}}
  await expect(next.retryPending('a')).rejects.toEqual(rejection)
  expect(requests[1]).toEqual(requests[0])
  expect(next.pendingTarget('a')).toBeUndefined()
})

it('business-session clear makes retained retry inaccessible and an old response cannot clear a new generation request',async()=>{
  let fail=true;let finish!:()=>void
  const requests:any[]=[]
  http.defaults.adapter=config=>{
    requests.push(JSON.parse(config.data))
    if(fail)return Promise.reject(new Error('reply lost'))
    return new Promise(resolve=>{finish=()=>resolve({config,headers:{},status:201,statusText:'',data:{data:[]}})})
  }
  const first=scope.run(()=>useVisitOrdering())!
  first.drafts.replace('a',{soap:2})
  await expect(first.submitSnapshot(first.drafts.capture('a',3))).rejects.toThrow()
  fail=false
  const old=first.retryPending('a').catch(()=>undefined)
  clearBusinessSession()
  expect(first.pendingTarget('a')).toBeUndefined()
  await expect(first.retryPending('a')).rejects.toThrow()
  expect(requests).toHaveLength(2)
  fail=true
  const next=scope.run(()=>useVisitOrdering())!
  next.drafts.replace('a',{water:5})
  await expect(next.submitSnapshot(next.drafts.capture('a',7))).rejects.toThrow()
  finish();await old
  expect(next.pendingTarget('a')?.quantities).toEqual({water:5})
  expect(first.pendingTarget('a')).toBeUndefined()
  await expect(first.retryPending('a')).rejects.toThrow('登录或经营期已变化')
  expect(requests).toHaveLength(3)
})
