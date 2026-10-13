import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { http } from '../../api/http'
import { businessGeneration, clearBusinessSession } from '../../business/state'
import { printServiceJob } from './printing'
const originalAdapter = http.defaults.adapter
beforeEach(() => { clearBusinessSession(); setActivePinia(createPinia()) })
afterEach(() => { http.defaults.adapter = originalAdapter; delete (window as any).xiquan; clearBusinessSession(); vi.restoreAllMocks() })
function desktop(print = vi.fn(async () => ({success:true}))) {
  ;(window as any).xiquan = {printReceipt:print,setBusinessBusy:vi.fn(async () => ({businessBusyReason:null}))}
  return print
}
it('browser ordering succeeds without pretending to silently print',async () => {
  const adapter = vi.fn(); http.defaults.adapter = adapter
  const result = await printServiceJob('job','automatic',undefined,businessGeneration.capture())
  expect(result.state).toBe('failed'); expect(result.message).toContain('下单成功')
  expect(adapter).not.toHaveBeenCalled()
})
it('once-only authorization is checked before calling the local printer',async () => {
  const printer = desktop()
  http.defaults.adapter = async config => ({config,headers:{},status:200,statusText:'',
    data:{data:{id:'attempt',print_allowed:false,receipt:{receipt_kind:'order'}}}})
  const result = await printServiceJob('job','automatic','XP-58',businessGeneration.capture())
  expect(result.state).toBe('skipped'); expect(printer).not.toHaveBeenCalled()
})
it('printer failure records only the printing result, never repeats an order',async () => {
  const printer = desktop(vi.fn(async () => ({success:false,error:'USB offline'})) as any)
  const calls:any[]=[]
  http.defaults.adapter = async config => {
    calls.push(config.url)
    return {config,headers:{},status:201,statusText:'',data:{data:{id:'attempt',print_allowed:true,
      receipt:{receipt_kind:'order',wristband_number:'001'}}}}
  }
  const result = await printServiceJob('job','automatic','XP-58',businessGeneration.capture())
  expect(result.state).toBe('failed'); expect(printer).toHaveBeenCalledTimes(1)
  expect(calls).toEqual(['/service-print-jobs/job/attempts','/service-print-jobs/job/attempts/attempt/result'])
  expect((window.xiquan!.setBusinessBusy as any).mock.calls.at(-1)[0]).toBeNull()
})
it('lost result acknowledgement is uncertain and never prints again automatically',async () => {
  const printer = desktop()
  http.defaults.adapter = async config => {
    if (String(config.url).endsWith('/result')) throw new Error('timeout')
    return {config,headers:{},status:201,statusText:'',data:{data:{id:'attempt',print_allowed:true,receipt:{receipt_kind:'order'}}}}
  }
  const result = await printServiceJob('job','automatic',undefined,businessGeneration.capture())
  expect(result.state).toBe('uncertain'); expect(printer).toHaveBeenCalledTimes(1)
})
it('an account switch before the attempt response prevents printing',async () => {
  const printer = desktop(); let finish!:() => void
  http.defaults.adapter = config => new Promise(resolve => {finish = () => resolve({config,headers:{},status:201,
    statusText:'',data:{data:{id:'attempt',print_allowed:true,receipt:{receipt_kind:'order'}}}})})
  const pending = printServiceJob('job','automatic',undefined,businessGeneration.capture())
  await new Promise(resolve => setTimeout(resolve,0))
  clearBusinessSession(); finish()
  expect((await pending).state).toBe('skipped'); expect(printer).not.toHaveBeenCalled()
})
