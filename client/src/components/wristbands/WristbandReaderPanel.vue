<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { apiData, apiErrorMessage, http } from '../../api/http'
import { businessGeneration, businessState, canCapability, onBusinessSessionClear } from '../../business/state'
import { createChipReceiver, isEditingTarget } from '../../domain/wristband-reader/keyboard'
import { createScanQueue } from '../../domain/wristband-reader/queue'

interface ScanSession { id:string; numbers:string[]; expires_at:string }
interface ScanResult { opened:boolean; wristband_number:string; visit_id:string; session:ScanSession|null; server_time:string }
interface ScanRequest { chip_uid:string; link_mode:boolean; idempotency_key:string; session_id?:string }
interface QueuedScan { uid:string; link:boolean; request?:ScanRequest }
const props=defineProps<{enabled:boolean;paused:boolean}>()
const emit=defineEmits<{changed:[]}>()
const generation=businessGeneration.capture()
const link=ref(false), session=ref<ScanSession|null>(null), now=ref(Date.now()), clockOffset=ref(0)
const notice=ref(''), error=ref(''), busy=ref(false), queued=ref(0), retry=ref<QueuedScan|null>(null)
const focused=ref(false), modal=ref(false), visible=ref(document.visibilityState!=='hidden'), online=ref(navigator.onLine)
let active=true, timer:number|undefined, observer:MutationObserver|undefined
const allowed=computed(()=>props.enabled && canCapability('visit_open') && businessGeneration.isCurrent(generation)
  && businessState.value?.maintenance===false)
const paused=computed(()=>props.paused||focused.value||modal.value)
const seconds=computed(()=>session.value ? Math.max(0,Math.ceil((Date.parse(session.value.expires_at)-now.value-clockOffset.value)/1000)):0)
const status=computed(()=>!online.value?'网络已断开，暂停刷卡':retry.value?'上次请求未确认，请重试或重新查询'
  :paused.value?'操作完成后恢复刷卡':busy.value?`正在开牌${queued.value>1?`，还有 ${queued.value-1} 张排队`:''}`:'准备刷卡')

function ready() {return active && allowed.value && !paused.value && visible.value && online.value && !retry.value}
function blockedModal() {
  return Array.from(document.querySelectorAll('[aria-modal="true"]')).some(element=>{
    const overlay=element.closest('.el-overlay') || element
    return element.getAttribute('aria-hidden')!=='true' && getComputedStyle(overlay).display!=='none'
  })
}
function activity() { focused.value=isEditingTarget(document.activeElement); modal.value=blockedModal(); if(paused.value) receiver.reset() }
function reset() { receiver.reset(); queue.clear(); session.value=null; retry.value=null; error.value=''; notice.value=''; queued.value=0; busy.value=false }
const queue=createScanQueue<QueuedScan,ScanResult>(async item=>{
  if(!active||!allowed.value||!visible.value||!online.value) throw new Error('页面或网络状态已变化，请重新刷卡')
  busy.value=true;queued.value=queue.pending
  // Resolve the prior group only when this card reaches the head of the queue.
  item.request ||= {chip_uid:item.uid,link_mode:item.link,idempotency_key:crypto.randomUUID(),
    ...(item.link&&session.value&&seconds.value>0?{session_id:session.value.id}:{})}
  return apiData<ScanResult>(await http.post('/wristband-reader/scan',item.request))
},result=>{
  clockOffset.value=Date.parse(result.server_time)-Date.now();now.value=Date.now();session.value=result.session
  notice.value=`${result.wristband_number} 号${result.opened?'已开牌':'已激活，未重复收费'}`
  busy.value=queue.pending>1;queued.value=Math.max(0,queue.pending-1);error.value='';retry.value=null
  if(result.opened) emit('changed')
},(failure,item)=>{
  busy.value=false;queued.value=0;error.value=apiErrorMessage(failure)
  // Retry retains exact body+identity, including a potentially committed opening.
  if(allowed.value && active) retry.value=item
},12)
const receiver=createChipReceiver({canRead:ready,onRead:uid=>{
  if(!queue.enqueue({uid,link:link.value})) error.value='刷卡队列已满，请稍后重新刷这张手牌'
  queued.value=queue.pending
}})
function keydown(event:KeyboardEvent) {
  activity()
  if(isEditingTarget(event.target)||isEditingTarget(document.activeElement)) {receiver.reset();return}
  receiver.keydown(event)
}
function visibility() {visible.value=document.visibilityState!=='hidden';if(!visible.value){reset();link.value=false}}
function network() {online.value=navigator.onLine;if(!online.value){reset();link.value=false;error.value='网络已断开，不会自动补开手牌'}}
function retryRequest() {
  const item=retry.value
  if(!item||!online.value||!allowed.value||paused.value) return
  retry.value=null;error.value='';queue.enqueue(item);queued.value=queue.pending
}
watch(link,()=>reset())
watch(allowed,value=>{if(!value){reset();link.value=false}})
watch(()=>props.paused,()=>receiver.reset())
onBusinessSessionClear(()=>{reset();link.value=false})
onMounted(()=>{
  window.addEventListener('keydown',keydown,true);window.addEventListener('offline',network);window.addEventListener('online',network)
  document.addEventListener('visibilitychange',visibility);document.addEventListener('focusin',activity);document.addEventListener('focusout',activity)
  observer=new MutationObserver(activity);observer.observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['style','aria-hidden']})
  timer=window.setInterval(()=>{now.value=Date.now();if(session.value&&seconds.value===0) session.value=null},500)
})
onBeforeUnmount(()=>{
  active=false;reset();observer?.disconnect();if(timer) window.clearInterval(timer)
  window.removeEventListener('keydown',keydown,true);window.removeEventListener('offline',network);window.removeEventListener('online',network)
  document.removeEventListener('visibilitychange',visibility);document.removeEventListener('focusin',activity);document.removeEventListener('focusout',activity)
})
</script>

<template>
  <section v-if="allowed" class="reader-panel" aria-label="手牌刷卡开牌">
    <div class="reader-status"><span :class="['reader-dot',{paused:paused||!online||retry}]" /><strong>{{status}}</strong><span>刷入已录入的手牌，按普通门票开牌</span></div>
    <label class="link-toggle"><input v-model="link" data-testid="scan-link" type="checkbox" :disabled="paused||!online" />刷卡联动</label>
    <div v-if="session" class="reader-group"><strong>{{session.numbers.join('、')}}</strong><span>{{session.numbers.length}} 人 · {{seconds}} 秒内可继续加入（男女浴可联动）</span><button type="button" @click="reset">结束接收</button></div>
    <p v-if="notice" class="reader-notice" role="status">{{notice}}</p>
    <p v-if="error" class="reader-error" role="alert">{{error}}</p>
    <div v-if="retry" class="reader-retry"><button type="button" :disabled="!online||paused" @click="retryRequest">重试同一请求</button><button type="button" @click="reset();emit('changed')">重新查询后继续刷卡</button><span>重试不会重复收门票；后续排队手牌需要重新刷。</span></div>
  </section>
</template>

<style scoped>
.reader-panel{display:flex;align-items:center;gap:14px 24px;flex-wrap:wrap;padding:14px 18px;margin-bottom:18px;border:1px solid var(--xq-border);border-radius:12px;background:var(--xq-bg-1,#fff)}
.reader-status{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.reader-status>span:last-child{color:var(--xq-text-3);font-size:13px}.reader-dot{width:9px;height:9px;background:#24846b;border-radius:50%}.reader-dot.paused{background:#bd8a43}
.link-toggle{margin-left:auto;display:flex;align-items:center;gap:8px;font-weight:600}.link-toggle input{width:17px;height:17px;accent-color:var(--xq-primary)}
.reader-group,.reader-retry{width:100%;display:flex;gap:14px;align-items:center;flex-wrap:wrap}.reader-group strong{font-size:19px}.reader-group span,.reader-retry span{font-size:13px;color:var(--xq-text-3)}
.reader-panel button{border:1px solid var(--xq-border);border-radius:6px;padding:7px 12px;background:white;color:var(--xq-primary);cursor:pointer}.reader-notice,.reader-error{width:100%;margin:0;font-size:14px}.reader-notice{color:#24846b}.reader-error{color:#b64137}
</style>
