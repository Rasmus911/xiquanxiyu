import { apiData, apiErrorMessage, http } from '../../api/http'
import { businessGeneration } from '../../business/state'
import { useRuntimeStore } from '../../stores/runtime'

export type PrintOutcome = {state:'success'|'failed'|'uncertain'|'skipped'; message:string}
type PrintMode = 'automatic'|'manual'
type Attempt = {id:string; print_allowed:boolean; receipt:Record<string,unknown>}

async function printJob(path:string, mode:PrintMode, printerName:string|undefined,
  generation:number, service:boolean):Promise<PrintOutcome> {
  const current = () => businessGeneration.isCurrent(generation)
  const business = service ? '下单成功' : '结账已成功'
  const skipped:PrintOutcome = {state:'skipped',message:'登录状态已变化，未开始打印'}
  if (!current()) return skipped
  if (!window.xiquan?.printReceipt) return {state:'failed',message:`${business}，请在桌面端打印`}
  let release = async () => {}
  let paperStarted = false
  try {
    release = await useRuntimeStore().setBusinessBusy('正在打印小票，请勿更新或退出')
    if (!current()) return skipped
    const attempt = apiData<Attempt>(await http.post(path, {
      request_key:mode === 'automatic' ? 'automatic-once' : crypto.randomUUID(), mode,
    }))
    if (!current()) return skipped
    if (attempt.print_allowed !== true) return {state:'skipped',message:'本次自动打印已提交，请在小票补打页核对'}
    if (typeof attempt.id !== 'string' || !attempt.id || !attempt.receipt) throw new Error('打印授权响应不完整')
    paperStarted = true
    let result:PrintResult
    try { result = await window.xiquan.printReceipt(attempt.receipt,printerName) }
    catch (error) { result = {success:false,error:apiErrorMessage(error)} }
    if (!current()) return {state:'uncertain',message:'账号已切换，打印结果请在补打页核对，请勿重复下单或收款'}
    const success = result?.success === true
    const error = success ? undefined : String(result?.error || '打印失败').slice(0,500)
    await http.post(`${path}/${encodeURIComponent(attempt.id)}/result`,{success,...(error ? {error} : {})})
    return success ? {state:'success',message:'小票已提交打印机'}
      : {state:'failed',message:`${business}，小票待补打：${error}`}
  } catch (error) {
    if (!current() && !paperStarted) return skipped
    return paperStarted ? {state:'uncertain',message:`${business}，打印结果未确认，请到补打页核对，不要重复下单或收款`}
      : {state:'failed',message:`${business}，小票待补打：${apiErrorMessage(error)}`}
  } finally { await release() }
}

export function printServiceJob(jobId:string,mode:PrintMode,printerName:string|undefined,generation:number) {
  return printJob(`/service-print-jobs/${encodeURIComponent(jobId)}/attempts`,mode,printerName,generation,true)
}
export function printSettlementJob(settlementId:string,mode:PrintMode,printerName:string|undefined,generation:number) {
  return printJob(`/checkout/${encodeURIComponent(settlementId)}/print-attempts`,mode,printerName,generation,false)
}
