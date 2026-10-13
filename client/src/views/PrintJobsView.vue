<script setup lang="ts">
import {computed,onBeforeUnmount,onMounted,reactive,ref} from 'vue'
import {ElMessage} from 'element-plus'
import {apiData,apiErrorMessage,http} from '../api/http'
import {businessGeneration,canCapability,onBusinessSessionClear,useBusinessGuard} from '../business/state'
import {useAuthStore} from '../stores/auth'
import {usePageRefresh} from '../composables/usePageRefresh'
import {subscribeRealtime} from '../realtime/events'
import {formatBusinessTime} from '../format/business-time'
import {receiptDayClock} from '../domain/receipts/day'
import {printServiceJob,printSettlementJob} from '../domain/receipts/printing'
import AppPageHeader from '../components/app/AppPageHeader.vue'

type Kind='order'|'settlement'
type Row={id:string;settlement_id?:string;settlement_number?:string;wristband_number?:string;employee_name?:string;
 employee_username?:string;created_at:string;amount?:string;status:string;attempts:number;last_error?:string}
type Page={items:Row[];total:number;server_time:string;expires_at:string}
const auth=useAuthStore();const guard=useBusinessGuard()
const tabs=computed(()=>[...(canCapability('service_receipt_reprint')?[{kind:'order' as Kind,label:'下单小票'}]:[]),
 ...(canCapability('settlement_receipt_reprint')?[{kind:'settlement' as Kind,label:'结账小票'}]:[])])
const active=ref<Kind>(canCapability('service_receipt_reprint')?'order':'settlement')
const makePage=()=>({rows:[] as Row[],total:0,page:1,loading:false,error:'',clock:null as ReturnType<typeof receiptDayClock>|null})
const lists=reactive({order:makePage(),settlement:makePage()})
const current=computed(()=>lists[active.value]);const printingId=ref('')
let timer:number|undefined;let unsubscribe:(()=>void)|undefined;let stopped=false
function clear(){for(const value of Object.values(lists)){value.rows=[];value.total=0;value.page=1;value.clock=null}}
onBusinessSessionClear(clear)
function expiredPages(){let expired=false;for(const value of Object.values(lists)){
 if(value.clock?.expired()){value.rows=[];value.total=0;value.clock=null;value.page=1;expired=true}
}return expired}
function schedule(){
 if(timer)window.clearTimeout(timer)
 if(stopped)return
 const clocks=Object.values(lists).flatMap(value=>value.clock?[value.clock.delay()]:[])
 timer=window.setTimeout(()=>{if(expiredPages())void load();else schedule()},Math.min(60_000,...clocks.map(delay=>Math.max(1,delay))))
}
async function load(kind=active.value){
 if(!tabs.value.some(tab=>tab.kind===kind))return
 const valid=guard('load-'+kind);const value=lists[kind];const page=value.page
 value.loading=true;value.error=''
 try{
  const params=new URLSearchParams({paged:'true',page:String(page),page_size:'10'})
  for(const status of ['pending','failed','success'])params.append('status',status)
  const response=apiData<Page>(await http.get(kind==='order'?'/service-print-jobs':'/checkout/print-jobs',{params}))
  if(!valid())return
  value.clock=receiptDayClock(response);value.rows=value.clock.expired()?[]:response.items
  value.total=value.clock.expired()?0:response.total;schedule()
 }catch(error){if(valid()){value.rows=[];value.total=0;value.error=apiErrorMessage(error)}}
 finally{if(valid())value.loading=false}
}
function select(kind:Kind){active.value=kind;expiredPages();void load(kind)}
function changePage(page:number){current.value.page=page;void load()}
async function reprint(row:Row){
 if(printingId.value)return
 const kind=active.value;const value=lists[kind];const valid=guard('reprint');const generation=businessGeneration.capture()
 if(!value.clock||value.clock.expired()){expiredPages();ElMessage.warning('已跨过北京时间午夜，请刷新当日小票');void load();return}
 printingId.value=row.id
 try{
  const printer=auth.terminal?.printer_name||localStorage.getItem('xiquan_printer_name')||undefined
  const result=kind==='order'?await printServiceJob(row.id,'manual',printer,generation)
   :await printSettlementJob(row.settlement_id!,'manual',printer,generation)
  if(!valid())return
  result.state==='success'?ElMessage.success('小票已提交打印机'):ElMessage.warning(result.message)
  await load(kind)
 }finally{if(valid())printingId.value=''}
}
function visible(){if(document.visibilityState==='visible'){expiredPages();void load()}}
usePageRefresh(()=>load())
onMounted(()=>{void load();document.addEventListener('visibilitychange',visible)
 unsubscribe=subscribeRealtime(['checkout','visits'],()=>{expiredPages();void load()})})
onBeforeUnmount(()=>{stopped=true;if(timer)window.clearTimeout(timer);unsubscribe?.();document.removeEventListener('visibilitychange',visible)})
</script>

<template>
 <div class="page">
  <AppPageHeader title="小票补打" description="仅保留北京时间当天小票，午夜过期。补打不新增消费或再次扣款。">
   <template #actions><el-button :disabled="!!printingId" @click="load()">刷新</el-button></template>
  </AppPageHeader>
  <el-card shadow="never">
   <div class="receipt-toolbar">
    <div class="receipt-tabs" role="tablist">
     <button v-for="tab in tabs" :key="tab.kind" role="tab" :aria-selected="active===tab.kind" :class="{active:active===tab.kind}"
      :data-testid="`receipt-tab-${tab.kind}`" :disabled="!!printingId" @click="select(tab.kind)">{{tab.label}}</button>
    </div>
    <el-pagination :current-page="current.page" :page-size="10" :total="current.total" layout="total, prev, pager, next" :disabled="!!printingId" @current-change="changePage" />
   </div>
   <p class="receipt-note">{{active==='order'?'下单小票：只列本次加单，非收款凭证。':'结账小票：订单已收款，仅重新打印。'}}</p>
   <el-alert v-if="current.error" :title="current.error" type="error" :closable="false" />
   <el-table v-loading="current.loading" :data="current.rows" row-key="id">
    <el-table-column label="时间" min-width="165"><template #default="{row}">{{formatBusinessTime(row.created_at)}}</template></el-table-column>
    <template v-if="active==='order'">
     <el-table-column prop="wristband_number" label="手牌号" min-width="95"><template #default="{row}"><strong class="receipt-band">{{row.wristband_number}}</strong></template></el-table-column>
     <el-table-column label="开单员工" min-width="165"><template #default="{row}">{{row.employee_name}} <small>{{row.employee_username}}</small></template></el-table-column>
    </template>
    <template v-else><el-table-column prop="settlement_number" label="结算单号" min-width="165" /><el-table-column label="收款金额" min-width="100"><template #default="{row}">¥{{row.amount}}</template></el-table-column></template>
    <el-table-column label="打印状态" width="105"><template #default="{row}"><el-tag :type="row.status==='success'?'success':row.status==='failed'?'danger':'warning'">{{row.status==='success'?'已打印':row.status==='failed'?'打印失败':'待打印'}}</el-tag></template></el-table-column>
    <el-table-column prop="attempts" label="打印次数" width="90" />
    <el-table-column prop="last_error" label="失败原因" min-width="150" show-overflow-tooltip />
    <el-table-column label="操作" width="120" fixed="right"><template #default="{row}"><el-button :data-testid="`receipt-reprint-${row.id}`" type="primary" plain :loading="printingId===row.id" :disabled="!!printingId&&printingId!==row.id" @click="reprint(row)">补打</el-button></template></el-table-column>
   </el-table>
   <el-empty v-if="!current.loading&&!current.rows.length&&!current.error" description="当天暂无该类型小票" />
  </el-card>
 </div>
</template>
<style scoped>
.receipt-toolbar{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}
.receipt-tabs{display:flex;gap:6px}.receipt-tabs button{border:1px solid var(--el-border-color);background:transparent;color:var(--el-text-color-regular);padding:10px 16px;border-radius:6px;cursor:pointer}
.receipt-tabs button.active{background:var(--el-color-primary-light-9);border-color:var(--el-color-primary);color:var(--el-color-primary);font-weight:600}
.receipt-note{color:var(--el-text-color-secondary);font-size:13px;margin:18px 0 12px}.receipt-band{font-size:20px}small{display:block;color:var(--el-text-color-secondary)}
</style>

