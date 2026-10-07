<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { costPreview, warningPreview } from '../domain/inventory/receiving'
import { canAccess, permissions, useBusinessGuard } from '../business/state'
import { dataOf, errorMessage, http } from '../api'
import InventoryAddSheet from '../components/inventory/InventoryAddSheet.vue'
import MobileTopbar from '../components/navigation/MobileTopbar.vue'
import MobileState from '../components/common/MobileState.vue'
import { clearPendingOperationKey, pendingOperationKey } from '../idempotency'
import { scopedMobileCapabilities } from '../mobile-management'
import { previewStockQuantity, stockConversionError, validQuantity } from '../domain/inventory/quantity'
import { useBusinessStore } from '../stores/business'
import { useSessionStore } from '../stores/session'
import type { StockItem, StockUsage } from '../types'
const guard = useBusinessGuard(); const business=useBusinessStore();const session=useSessionStore()
const allowed=computed(()=>canAccess('inventory:write')&&scopedMobileCapabilities(session.employee?.capabilities,permissions.value).inventory_manage)
const search=ref('');const message=ref('');const receiving=ref<StockItem|null>(null)
const editing=ref<StockItem|null>(null);const editorOpen=ref(false)
const usage=ref<StockUsage[]>([])
interface Movement{id:string;stock_item_id:string;movement_type:string;quantity:string;input_quantity:string;input_unit:string;conversion_factor:string;base_unit:string;package_unit:string;reason:string;cost?:{id:string;unit_cost:string;total_cost:string;base_unit_cost:string}|null}
const movements=ref<Movement[]>([])
const form=reactive({name:'',base_unit:'',package_unit:'',units_per_package:'1',opening_quantity:'0',opening_unit:'base',unit_cost:'',master_unit_cost:'',password:''})
const page=ref(1),costReceipt=ref<Movement|null>(null),costInput=ref(''),costPassword=ref('')
const paged=computed(()=>rows.value.slice((page.value-1)*10,page.value*10))
watch(search,()=>{page.value=1})
watch(()=>form.opening_unit,()=>{form.unit_cost=''})
const openingCost=computed(()=>costPreview(form.opening_quantity,form.unit_cost,form.opening_unit==='package'?form.units_per_package:'1'))
const correctedCost=computed(()=>costReceipt.value?costPreview(costReceipt.value.input_quantity,costInput.value,costReceipt.value.conversion_factor):null)
const receiptPasswordRequired=computed(()=>!!costReceipt.value?.cost&&!!correctedCost.value&&Number(costInput.value)!==Number(costReceipt.value.cost.unit_cost))
const validReceiptCost=computed(()=>!!correctedCost.value&&(!receiptPasswordRequired.value||!!costPassword.value.trim()))
const rows=computed(()=>business.inventory.filter(row=>!search.value.trim()||`${row.name}${row.category}`.includes(search.value.trim())))
watch(()=>rows.value.length,count=>{page.value=Math.min(page.value,Math.max(1,Math.ceil(count/10)))})
const low=computed(()=>business.inventory.filter(row=>Number(row.stock_quantity)<=Number(row.low_stock_threshold)).length)
const preview=computed(()=>previewStockQuantity(form.opening_quantity,form.opening_unit,form.units_per_package))
const openingError=computed(()=>{
  if(!validQuantity(form.units_per_package))return '每包装单位数须为正数，最多三位小数且小于10亿'
  if(!editing.value&&form.unit_cost.trim()&&!openingCost.value)return '成本须为非负金额，最多两位小数；有入库数量才能记成本'
  return editing.value?'':stockConversionError(form.opening_quantity,form.opening_unit,form.units_per_package,true)
})
const masterCost=computed(()=>costPreview('1',form.master_unit_cost,'1')?.total)
const masterCostError=computed(()=>editing.value&&((form.master_unit_cost.trim()&&!masterCost.value)||(!form.master_unit_cost.trim()&&editing.value.unit_cost!=null))?'成本须为非负金额，最多两位小数且小于100亿元，已设置成本不可清空':'')
const masterCostChanged=computed(()=>!!editing.value&&!!masterCost.value&&(editing.value.unit_cost==null||Number(masterCost.value)!==Number(editing.value.unit_cost)))
const passwordRequired=computed(()=>masterCostChanged.value&&editing.value?.unit_cost!=null)
const validForm=computed(()=>form.name.trim()&&form.base_unit.trim()&&validQuantity(form.units_per_package)&&!openingError.value&&!masterCostError.value&&(!passwordRequired.value||form.password.trim()))
async function load(){
  if(!allowed.value)return
  const current=guard('load');if(!current())return
  try{
    await business.loadInventory();if(!current())return
    const [usageResponse,movementResponse]=await Promise.all([http.get('/inventory/usage'),http.get('/inventory/stock-movements')]);if(!current())return
    usage.value=dataOf<StockUsage[]>(usageResponse);movements.value=dataOf(movementResponse)
  }catch(cause){if(current())message.value=errorMessage(cause)}
}
function openEditor(item:StockItem|null){
  if(!allowed.value||business.inventorySaving)return
  editing.value=item;Object.assign(form,item?{...item,opening_quantity:'0',opening_unit:'base',unit_cost:'',master_unit_cost:item.unit_cost??'',password:''}:{name:'',base_unit:'',package_unit:'',units_per_package:'1',opening_quantity:'0',opening_unit:'base',unit_cost:'',master_unit_cost:'',password:''});editorOpen.value=true
}
async function write(method:'post'|'patch'|'delete',url:string,body:Record<string,unknown>){
  if(!allowed.value||business.inventorySaving)return false
  const current=guard('write');if(!current())return false
  const {password:_password,...fingerprintBody}=body
  const scope=`stock:${url}`;const key=pendingOperationKey(scope,JSON.stringify(fingerprintBody));const release=business.beginBusinessOperation('inventory')
  try{
    dataOf(await http.request({method,url,data:body,headers:{'Idempotency-Key':key}}));if(!current())return false
    clearPendingOperationKey(scope);message.value='库存已保存';return true
  }catch(cause){if(current()){
    const status=(cause as {response?:{status:number}}).response?.status
    if(status&&status>=400&&status<500)clearPendingOperationKey(scope)
    message.value=errorMessage(cause)
  }return false}finally{release()}
}
async function saveMaster(){
  if(!validForm.value)return
  const body:Record<string,unknown>={name:form.name.trim(),package_unit:form.package_unit.trim(),units_per_package:form.units_per_package}
  const item=editing.value
  if(item){body.version=item.version;if(masterCostChanged.value){body.unit_cost=masterCost.value;if(passwordRequired.value)body.password=form.password}}
  else{body.base_unit=form.base_unit.trim();if(Number(form.opening_quantity)>0){body.opening_quantity=form.opening_quantity;body.opening_unit=form.opening_unit;if(form.unit_cost.trim())body.unit_cost=form.unit_cost.trim()}}
  if(await write(item?'patch':'post',item?`/inventory/stock-items/${item.id}`:'/inventory/stock-items',body)){editorOpen.value=false;editing.value=null;await load()}
}
async function receive(value:{quantity:string;input_unit:string;reason:string;movement_type:string;unit_cost?:string}){
  const item=receiving.value;if(!item)return
  const conversionError=stockConversionError(value.quantity,value.input_unit,item.units_per_package)
  if(conversionError){message.value=conversionError;return}
  if(await write('post','/inventory/stock-adjust',{stock_item_id:item.id,version:item.version,...value})){receiving.value=null;await load()}
}
function editCost(row:Movement){costReceipt.value=row;costInput.value=row.cost?.unit_cost||'';costPassword.value=''}
async function saveCost(){const row=costReceipt.value;if(!row||!validReceiptCost.value)return;if(await write('post',`/inventory/stock-movements/${row.id}/cost`,{unit_cost:costInput.value.trim(),expected_cost_id:row.cost?.id||null,...(receiptPasswordRequired.value?{password:costPassword.value}:{})})){costReceipt.value=null;costPassword.value='';await load()}}
async function archive(item:StockItem){
  if(!allowed.value||business.inventorySaving)return
  const nonzero=Number(item.stock_quantity)!==0
  if(!window.confirm(nonzero?`删除/归档${item.name}，将报损 ${item.stock_quantity} ${item.base_unit} 并保留历史记录。确认吗？`:`确认归档${item.name}并保留历史记录？`))return
  if(await write('delete',`/inventory/stock-items/${item.id}`,{version:item.version,confirm_writeoff:nonzero}))await load()
}
function back(event:Event){if(!editorOpen.value&&!receiving.value&&!costReceipt.value)return;event.preventDefault();if(!business.inventorySaving){editorOpen.value=false;receiving.value=null;costReceipt.value=null}}
function changed(event:Event){if((event as CustomEvent<string[]>).detail.includes('inventory'))void load()}
onMounted(()=>{document.addEventListener('xiquan:back-request',back);window.addEventListener('xiquan:domains-refreshed',changed);void load()})
onBeforeUnmount(()=>{document.removeEventListener('xiquan:back-request',back);window.removeEventListener('xiquan:domains-refreshed',changed)})
</script>
<template>
  <div><MobileTopbar title="库存管理" subtitle="独立实物库存 · 按基本单位记账"/>
    <main class="mobile-page">
      <MobileState v-if="!allowed" kind="error" title="无权访问库存管理"/>
      <template v-else>
        <div v-if="message" class="notice">{{message}}</div>
        <div class="mini-metrics"><article><span>库存项目</span><strong>{{business.inventory.length}}</strong></article><article><span>低库存</span><strong>{{low}}</strong></article></div>
        <button data-testid="stock-create" :disabled="business.inventorySaving" @click="openEditor(null)">新增库存项目</button>
        <input v-model="search" class="mobile-input" placeholder="搜索库存"/>
        <MobileState v-if="business.loading&&!rows.length" kind="loading" title="正在读取库存"/>
        <MobileState v-else-if="business.error&&!rows.length" kind="error" title="库存读取失败" :description="business.error" @retry="load"/>
        <section class="mobile-card stock-list" data-testid="inventory-list"><div class="list-header"><strong>库存列表</strong><nav class="pagination" aria-label="库存分页"><button :disabled="page===1" @click="page--">上一页</button><span>{{page}} / {{Math.max(1,Math.ceil(rows.length/10))}} · 共{{rows.length}}项</span><button :disabled="page*10>=rows.length" @click="page++">下一页</button></nav></div>
        <section v-for="row in paged" :key="row.id" class="stock-row">
          <strong>{{row.name}}</strong><p>{{row.category}} · 现存 {{row.stock_quantity}} {{row.base_unit}}</p><p>{{row.package_spec}} · 每{{row.package_unit || '包装'}} {{row.units_per_package}} {{row.base_unit}} · 预警 {{row.low_stock_threshold}} {{row.base_unit}}</p>
          <p :data-testid="`stock-cost-${row.id}`">成本单价：{{row.unit_cost==null?'未设置':`¥${row.unit_cost} / ${row.base_unit}`}}</p>
          <button :data-testid="`stock-receive-${row.id}`" :disabled="business.inventorySaving" @click="receiving=row">入库</button>
          <button :data-testid="`stock-edit-${row.id}`" :disabled="business.inventorySaving" @click="openEditor(row)">编辑</button>
          <button class="archive-action" :data-testid="`stock-delete-${row.id}`" :disabled="business.inventorySaving" @click="archive(row)">归档</button>
        </section>
        </section>
        <section v-if="usage.length" class="mobile-card stock-row"><strong>有效订单使用频次</strong><p v-for="row in usage" :key="`${row.catalog_item_id}-${row.stock_item_id}`">{{row.catalog_name}} → {{row.stock_name}}：{{row.usage_count}} 次 · {{row.total_quantity}} {{row.base_unit}}{{row.is_most_used?' · 最常使用（含并列）':''}}</p></section>
        <details v-if="movements.length" class="mobile-card stock-row"><summary>库存流水 / 成本记录</summary><div v-for="row in movements" :key="row.id"><p>{{business.inventory.find(stock=>stock.id===row.stock_item_id)?.name || row.stock_item_id}} · {{row.movement_type}} · {{row.quantity}} {{row.base_unit}} · 输入 {{row.input_quantity}} {{row.input_unit==='package'?row.package_unit:row.base_unit}} × {{row.conversion_factor}} · {{row.reason}}</p><template v-if="['purchase','opening'].includes(row.movement_type)"><p>{{row.cost?`总成本 ¥${row.cost.total_cost} · 每${row.base_unit} ¥${row.cost.base_unit_cost}`:'成本未设置'}}</p><button :disabled="business.inventorySaving" @click="editCost(row)">{{row.cost?'更正成本':'补录成本'}}</button></template></div></details>
      </template>
    </main>
    <div v-if="allowed&&editorOpen" class="sheet-mask"><section class="sheet">
      <h3>{{editing?'编辑库存':'新增库存'}}</h3>
      <label>名称<input v-model="form.name" name="name" :disabled="business.inventorySaving"/></label>
      <label>基本消耗单位<input v-model="form.base_unit" name="base_unit" :disabled="!!editing||business.inventorySaving"/></label>
      <label>入库包装单位<input v-model="form.package_unit" name="package_unit" :disabled="business.inventorySaving"/></label>
      <label>每包装基本单位数<input v-model="form.units_per_package" name="units_per_package" inputmode="decimal" :disabled="business.inventorySaving"/></label>
      <template v-if="!editing"><label>期初数量（0 表示暂不入库）<input v-model="form.opening_quantity" name="opening_quantity" inputmode="decimal" :disabled="business.inventorySaving"/></label><label>期初输入单位<select v-model="form.opening_unit" :disabled="business.inventorySaving"><option value="base">{{form.base_unit}}</option><option v-if="form.package_unit" value="package">{{form.package_unit}}</option></select></label><p>折算期初：{{preview}} {{form.base_unit}}</p></template>
      <p v-if="openingError" role="alert">{{openingError}}</p>
      <template v-if="!editing"><p>自动预警 {{warningPreview(preview)}} {{form.base_unit}}（期初数量15%）</p><label>成本单价（元/{{form.opening_unit==='package'?form.package_unit:form.base_unit}}，可后补）<input v-model="form.unit_cost" name="unit_cost" inputmode="decimal" :disabled="business.inventorySaving" placeholder="未设置"/></label><p v-if="openingCost">总成本 ¥{{openingCost.total}} · 每{{form.base_unit}} ¥{{openingCost.baseUnit}}</p></template>
      <template v-if="editing"><label>库存成本单价（元/{{form.base_unit}}）<input v-model="form.master_unit_cost" name="master_unit_cost" inputmode="decimal" :disabled="business.inventorySaving" placeholder="未设置"/></label><p>首次设置免密码；修改已设置成本须验证本人登录密码。历史入库成本保留。</p><p v-if="masterCostError" role="alert">{{masterCostError}}</p><label v-if="passwordRequired">本人登录密码<input v-model="form.password" name="password" type="password" autocomplete="current-password" :disabled="business.inventorySaving"/></label><p>修改包装规格不会改变现存量及历史换算记录。</p></template>
      <div v-if="message" class="notice">{{message}}</div>
      <button data-testid="stock-save" :disabled="business.inventorySaving||!validForm" @click="saveMaster">保存</button><button :disabled="business.inventorySaving" @click="editorOpen=false">取消</button>
    </section></div>
    <InventoryAddSheet v-if="allowed" :item="receiving" :saving="business.inventorySaving" @close="receiving=null" @save="receive"/>
    <div v-if="allowed&&costReceipt" class="sheet-mask"><section class="sheet"><h3>补录 / 更正成本</h3><p>原入库 {{costReceipt.input_quantity}} {{costReceipt.input_unit==='package'?costReceipt.package_unit:costReceipt.base_unit}}，不改变数量。</p><label>单价（元/{{costReceipt.input_unit==='package'?costReceipt.package_unit:costReceipt.base_unit}}）<input v-model="costInput" :disabled="business.inventorySaving" inputmode="decimal"/></label><p v-if="correctedCost">总成本 ¥{{correctedCost.total}} · 基本单位 ¥{{correctedCost.baseUnit}}</p><p>首次补录免密码；修改已设置成本须验证本人登录密码。</p><label v-if="receiptPasswordRequired">本人登录密码<input v-model="costPassword" name="receipt_password" type="password" autocomplete="current-password" :disabled="business.inventorySaving"/></label><p>保留操作人、时间和前后金额。</p><button :disabled="business.inventorySaving||!validReceiptCost" @click="saveCost">保存成本</button><button :disabled="business.inventorySaving" @click="costReceipt=null;costPassword=''">取消</button></section></div>
  </div>
</template>
<style scoped>.stock-list{margin-top:12px;padding:12px}.list-header{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px}.pagination{display:flex;align-items:center;justify-content:flex-end;margin-left:auto;gap:4px;font-size:12px}.pagination button{margin:0;padding:6px}.stock-list>.stock-row{border-top:1px solid var(--m-border)}.archive-action{color:#b04444;margin-left:8px}details.stock-row{max-height:420px;overflow:auto}.stock-row>div{border-bottom:1px solid var(--m-border);padding:8px 0}</style>
<style scoped>.stock-row{padding:14px;margin-top:12px}.stock-row p{font-size:12px;color:var(--m-text-3)}button{min-height:42px;margin-right:8px;padding:8px 12px;border:1px solid var(--m-border);border-radius:7px;background:white;color:var(--m-primary)}.sheet-mask{position:fixed;z-index:70;inset:0;display:flex;align-items:end;background:#10203577}.sheet{width:100%;max-height:86vh;overflow:auto;padding:18px;background:white;border-radius:22px 22px 0 0}.sheet label{display:grid;gap:4px;margin:8px 0}.sheet input,.sheet select{min-height:44px;padding:8px;border:1px solid var(--m-border);border-radius:7px}</style>
