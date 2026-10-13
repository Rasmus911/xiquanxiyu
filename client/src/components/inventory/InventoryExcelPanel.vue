<script setup lang="ts">
import {computed,onMounted,reactive,ref,watch} from 'vue'
import {apiData,apiErrorMessage,http} from '../../api/http'
import {businessState,onBusinessSessionClear,useBusinessGuard} from '../../business/state'
import {pendingExcelWrite} from '../../domain/inventory/pending-excel'
import {formatStockQuantity} from '../../format/stock-quantity'

const props=defineProps<{canWrite:boolean;compact?:boolean}>()
const emit=defineEmits<{changed:[]}>()
interface PreviewRow {row_number:number;name:string;action:string;current_quantity?:string;target_quantity:string;base_unit?:string;package_unit?:string;current_package_cost?:string|null;target_package_cost?:string|null;requires_consumption_confirmation:boolean;decrease_percentage?:string}
interface Preview {preview_token:string;requires_password:boolean;rows:PreviewRow[];errors:{row_number:number;message:string}[]}
interface PendingRow {id:string;name:string;quantity:string;package_cost:string|null;target_stock_item_id?:string|null;requires_password?:boolean}
interface WriteRequest {url:string;body:Record<string,unknown>;key:string}
const plan=ref<Preview>(),source=ref<{source_base64:string;source_sha256:string}>(),pending=ref<PendingRow[]>([])
const confirmed=ref<number[]>([]),password=ref(''),busy=ref(false),message=ref(''),pendingOpen=ref(false)
const input=ref<HTMLInputElement>(),request=pendingExcelWrite,pendingPasswords=reactive<Record<string,string>>({})
const units=reactive<Record<string,{base_unit:string;package_unit:string;units_per_package:string}>>({})
const guard=useBusinessGuard(),editable=computed(()=>props.canWrite&&!!businessState.value&&!businessState.value.maintenance)
const ready=computed(()=>editable.value&&!busy.value&&!request.value&&!!plan.value&&!plan.value.errors.length&&
 plan.value.rows.every(row=>!row.requires_consumption_confirmation||confirmed.value.includes(row.row_number))&&
 (!plan.value.requires_password||!!password.value.trim()))
function clear(){plan.value=undefined;source.value=undefined;confirmed.value=[];password.value='';pendingOpen.value=false;request.value=undefined;pending.value=[];if(input.value)input.value.value=''}
onBusinessSessionClear(clear)
watch(editable,value=>{if(!value)clear()})
async function refresh(){const current=guard('pending');try{const rows=apiData<PendingRow[]>(await http.get('/inventory/excel/pending'));if(!current())return;pending.value=rows;for(const row of rows)units[row.id]??={base_unit:'',package_unit:'',units_per_package:'1'}}catch(error){if(current())message.value=apiErrorMessage(error)}}
async function preview(){
 if(!editable.value||busy.value||request.value||!source.value)return
 const current=guard('preview');busy.value=true;message.value='';password.value='';confirmed.value=[]
 try{const result=apiData<Preview>(await http.post('/inventory/excel/preview',source.value,{timeout:60000}));if(current())plan.value=result}
 catch(error){if(current()){plan.value=undefined;message.value=apiErrorMessage(error)}}finally{if(current())busy.value=false}
}
async function choose(event:Event){
 const file=(event.target as HTMLInputElement).files?.[0];if(!file||!editable.value||busy.value||request.value)return
 if(!/\.xlsx$/i.test(file.name)||file.size>10*1024*1024){message.value='请选择不超过10MB的 .xlsx 文件';return}
 const current=guard('file');busy.value=true;plan.value=undefined;message.value=''
 try{const buffer=await file.arrayBuffer(),bytes=new Uint8Array(buffer),hash=new Uint8Array(await crypto.subtle.digest('SHA-256',buffer));let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));if(current())source.value={source_base64:btoa(binary),source_sha256:Array.from(hash,b=>b.toString(16).padStart(2,'0')).join('')}}
 catch(error){if(current())message.value=apiErrorMessage(error)}finally{if(current())busy.value=false}
 if(current())await preview()
}
async function exportFile(){
 if(busy.value)return;const current=guard('export');busy.value=true;message.value=''
 try{const response=await http.get('/inventory/excel/export',{responseType:'blob',timeout:60000});if(!current())return;const url=URL.createObjectURL(new Blob([response.data],{type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}));const anchor=document.createElement('a');anchor.href=url;anchor.download='溪泉库存盘点表.xlsx';anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}catch(error){if(current())message.value=apiErrorMessage(error)}finally{if(current())busy.value=false}
}
async function write(value:WriteRequest){
 if(!editable.value||busy.value)return
 request.value=value;const current=guard('write');busy.value=true;message.value=''
 try{await http.post(value.url,value.body,{headers:{'Idempotency-Key':value.key},timeout:60000});if(!current())return;request.value=undefined;plan.value=undefined;source.value=undefined;password.value='';confirmed.value=[];message.value='库存已更新；新项目请补齐单位资料。';emit('changed');await refresh()}
 catch(error){if(!current())return;const status=(error as {response?:{status:number}}).response?.status;if(status&&status>=400&&status<500){request.value=undefined;password.value='';if(status===409){plan.value=undefined;message.value='库存或登录状态已改变，请重新预览后确认。';return}}message.value=apiErrorMessage(error)+(request.value?'；结果尚未确认，请重试原操作，不要重新导入。':'')}
 finally{if(current())busy.value=false}
}
async function apply(){if(!ready.value||!source.value||!plan.value)return;await write({url:'/inventory/excel/apply',key:crypto.randomUUID(),body:{...source.value,preview_token:plan.value.preview_token,confirmed_rows:[...confirmed.value],...(plan.value.requires_password?{password:password.value}:{})}})}
async function complete(row:PendingRow){const fields=units[row.id];if(!fields?.base_unit.trim()){message.value='请填写实际基本单位';return}if(row.requires_password&&!pendingPasswords[row.id]?.trim()){message.value='修改已有成本需本人登录密码';return}await write({url:`/inventory/excel/pending/${row.id}/complete`,key:crypto.randomUUID(),body:{...fields,base_unit:fields.base_unit.trim(),package_unit:fields.package_unit.trim(),...(row.requires_password?{password:pendingPasswords[row.id]}:{})}});pendingPasswords[row.id]=''}
async function cancel(row:PendingRow){if(request.value||!window.confirm(`取消待补资料“${row.name}”？不会删除现有库存。`))return;await write({url:`/inventory/excel/pending/${row.id}/cancel`,key:crypto.randomUUID(),body:{}})}
function acknowledge(row:number,event:Event){confirmed.value=(event.target as HTMLInputElement).checked?[...confirmed.value,row]:confirmed.value.filter(value=>value!==row)}
onMounted(refresh)
</script>
<template>
 <section class="excel-panel" :class="{'excel-panel--compact':compact}" aria-label="Excel人工盘点">
  <div class="excel-toolbar">
   <span class="excel-toolbar-label">Excel 盘点</span>
   <button type="button" :disabled="busy" @click="exportFile">导出库存表</button>
   <label v-if="editable" class="excel-upload" :class="{disabled:busy||!!request}">导入盘点表<input ref="input" class="excel-file-input" type="file" accept=".xlsx" :disabled="busy||!!request" @change="choose"></label>
   <button v-if="editable&&pending.length" data-testid="excel-pending" class="pending-button" type="button" :disabled="busy||!!request" @click="pendingOpen=!pendingOpen">补齐库存信息（{{pending.length}}）</button>
   <button v-if="editable&&request" type="button" :disabled="busy" @click="write(request)">重试原导入操作</button>
  </div>
  <p class="excel-note">数量填写袋、瓶等基本单位的最终结存，不是入库增量。成本填写每箱／包的成本；空白保留原成本，0表示免费。缺少单位的条目待补齐后入账。</p>
  <p v-if="busy" role="status">正在处理，请稍候…</p><p v-if="message" role="alert">{{message}}</p>
  <div v-if="plan" class="excel-preview">
   <h3>确认盘点变化</h3><p>以下更改统一提交；未出现在表格中的库存不会删除。</p>
   <p v-for="error in plan.errors" :key="error.row_number" class="excel-error">第{{error.row_number}}行：{{error.message}}</p>
   <div class="excel-scroll"><table><thead><tr><th>项目</th><th>当前 → 盘点数量</th><th>包装成本（元）</th><th>确认</th></tr></thead><tbody>
    <tr v-for="row in plan.rows" :key="row.row_number"><td>{{row.name}}<small v-if="['new','needs_units','already_pending'].includes(row.action)">待补齐单位资料</small></td><td>{{formatStockQuantity(row.current_quantity)}} → {{formatStockQuantity(row.target_quantity)}} {{row.base_unit}}</td><td>{{row.current_package_cost??'未设置'}} → {{row.target_package_cost??row.current_package_cost??'未设置'}}<small>{{row.package_unit}}</small></td><td><label v-if="row.requires_consumption_confirmation" class="excel-error"><input :data-testid="'excel-confirm-'+row.row_number" type="checkbox" :checked="confirmed.includes(row.row_number)" :disabled="busy||!!request" @change="acknowledge(row.row_number,$event)">是否是真的消耗了这么多？减少{{row.decrease_percentage}}%</label><span v-else>{{row.action==='unchanged'?'无变化':'已核对'}}</span></td></tr>
   </tbody></table></div>
   <label v-if="plan.requires_password">修改已有成本，请输入本人登录密码<input v-model="password" type="password" autocomplete="current-password" :disabled="busy||!!request"></label>
   <div class="excel-footer"><button v-if="!request" type="button" :disabled="busy" @click="preview">重新预览</button><button type="button" data-testid="excel-apply" :disabled="!ready" @click="apply">确认导入</button></div>
  </div>
  <button v-else-if="source&&!request" type="button" :disabled="busy||!editable" @click="preview">重新预览所选文件</button>
  <div v-if="pendingOpen&&editable" class="excel-pending-list"><h3>补齐库存信息</h3>
   <article v-for="row in pending" :key="row.id"><strong>{{row.name}}</strong><p>盘点数量 {{formatStockQuantity(row.quantity)}} · 包装成本 {{row.package_cost??'未设置'}} 元</p>
    <label>基本单位<input v-model="units[row.id]!.base_unit" :data-testid="'pending-base-'+row.id" placeholder="袋、瓶" :disabled="busy||!!request"></label>
    <label>包装单位<input v-model="units[row.id]!.package_unit" :data-testid="'pending-package-'+row.id" placeholder="箱、包（没有可留空）" :disabled="busy||!!request"></label>
    <label>每包装基本单位数<input v-model="units[row.id]!.units_per_package" :data-testid="'pending-factor-'+row.id" inputmode="decimal" :disabled="busy||!!request"></label>
    <label v-if="row.requires_password">本人登录密码<input v-model="pendingPasswords[row.id]" type="password" autocomplete="current-password" :disabled="busy||!!request"></label>
    <button type="button" :data-testid="'pending-complete-'+row.id" :disabled="busy||!!request" @click="complete(row)">补齐并入账</button><button type="button" :disabled="busy||!!request" @click="cancel(row)">取消此待补行</button>
   </article>
  </div>
 </section>
</template>
<style scoped>
.excel-panel{padding:16px 0;color:var(--el-text-color-primary,#40332d)}.excel-toolbar,.excel-footer{display:flex;flex-wrap:wrap;gap:10px;align-items:center}.excel-panel button,.excel-upload{padding:9px 14px;border:1px solid #d4c8bb;border-radius:7px;background:#fff;cursor:pointer;font:inherit}.excel-panel button:disabled{opacity:.5;cursor:not-allowed}.excel-upload input{display:block;max-width:230px;margin-top:6px}.excel-panel .pending-button{background:#bd3d35;color:#fff;border-color:#bd3d35}.excel-note{font-size:13px;color:#73665c;line-height:1.65}.excel-preview,.excel-pending-list{padding:16px;border:1px solid #ded4c8;background:#faf7f2;border-radius:9px;margin-top:12px}.excel-scroll{overflow:auto}.excel-panel table{width:100%;border-collapse:collapse;font-size:14px}.excel-panel td,.excel-panel th{text-align:left;padding:10px;border-bottom:1px solid #e5dcd2;min-width:140px}.excel-panel small{display:block;color:#776a60;margin-top:4px}.excel-error{color:#ad332b}.excel-footer{margin-top:14px;justify-content:flex-end}.excel-pending-list article{padding:14px 0;border-bottom:1px solid #ded4c8}.excel-panel label{font-size:14px}.excel-pending-list label{display:inline-block;max-width:210px;margin:6px 10px 10px 0}.excel-panel input:not([type=checkbox]):not([type=file]){display:block;padding:9px;border:1px solid #ccc;border-radius:5px;box-sizing:border-box;max-width:100%;width:100%;margin-top:5px}.excel-preview>label{display:block;max-width:360px;margin-top:12px}
</style>
<style scoped>
.excel-toolbar-label{font-size:13px;color:var(--xq-text-3,#73665c);margin-right:auto}
.excel-file-input{position:absolute!important;width:1px!important;height:1px!important;overflow:hidden;clip-path:inset(50%);margin:0!important}
.excel-upload{position:relative;display:inline-flex;align-items:center;min-height:36px;box-sizing:border-box}
.excel-upload:focus-within{outline:2px solid var(--xq-primary,#925a43);outline-offset:2px}
.excel-upload.disabled{opacity:.5;cursor:not-allowed}
.excel-panel--compact{margin:0 0 16px;padding:12px 16px;border:1px solid var(--xq-border,#ded4c8);border-radius:8px;background:var(--xq-surface,#fff)}
.excel-panel--compact .excel-toolbar{gap:8px}
.excel-panel--compact .excel-note{margin:8px 0 0;font-size:12px}
.excel-panel--compact button,.excel-panel--compact .excel-upload{padding:7px 12px;font-size:13px}
.excel-panel--compact .excel-toolbar>button:first-of-type{background:transparent}
.excel-toolbar .pending-button{margin-left:4px}
@media(max-width:640px){.excel-toolbar-label{width:100%}.excel-panel--compact{padding:12px}}
</style>
