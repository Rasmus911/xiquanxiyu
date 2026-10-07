<script setup lang="ts">
import { canCapability, useBusinessGuard } from '../business/state'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiData, apiErrorMessage, http } from '../api/http'
import AppPageHeader from '../components/app/AppPageHeader.vue'
import { clearPendingRequestKey, pendingRequestKey } from '../domain/requests/pending-key'
import { previewStockQuantity } from '../domain/inventory/quantity'
import { costPreview, warningPreview, receivingReasons } from '../domain/inventory/receiving'
import { pendingStockWrite } from '../domain/inventory/pending-write'
import { subscribeRealtime } from '../realtime/events'
import type { StockItem, StockMovement, StockUsage } from '../types'
import { formatBusinessTime } from '../format/business-time'
const guardBusinessOperation = useBusinessGuard()
const products=ref<StockItem[]>([]),movements=ref<StockMovement[]>([]),usage=ref<StockUsage[]>([])
const drawerOpen=ref(false),masterOpen=ref(false),editingId=ref(''),editingVersion=ref(0),saving=ref(false)
const keyword=ref(''),category=ref(''),includeInactive=ref(false),historyId=ref(''),page=ref(1)
const costOpen=ref(false),costReceipt=ref<StockMovement|null>(null),costInput=ref('')
const editingCost=ref<string|null>(null),authorizing=ref(false)
const form=reactive({stock_item_id:'',version:0,movement_type:'purchase',quantity:'1',input_unit:'base',reason:'采购入库',unit_cost:''})
const masterForm=reactive({name:'',category:'默认',base_unit:'',package_unit:'',units_per_package:'1',package_spec:'',low_stock_threshold:'0',opening_quantity:'0',opening_unit:'base',unit_cost:''})
let unsubscribeRealtime:(()=>void)|undefined
const pending = pendingStockWrite
const filtered=computed(()=>products.value.filter(row=>(!category.value||row.category===category.value)&&(!keyword.value.trim()||row.name.includes(keyword.value.trim()))))
const paged=computed(()=>filtered.value.slice((page.value-1)*10,page.value*10))
watch([keyword,category,includeInactive],()=>{page.value=1})
watch(()=>filtered.value.length,length=>{page.value=Math.min(page.value,Math.max(1,Math.ceil(length/10)))})
const openingCost=computed(()=>costPreview(masterForm.opening_quantity,masterForm.unit_cost,masterForm.opening_unit==='package'?masterForm.units_per_package:'1'))
const receivingCost=computed(()=>costPreview(form.quantity,form.unit_cost,form.input_unit==='package'?selectedStock.value?.units_per_package||'1':'1'))
const correctionCost=computed(()=>costReceipt.value?costPreview(costReceipt.value.input_quantity,costInput.value,costReceipt.value.conversion_factor):null)
const summary=computed(()=>{
  const active=products.value.filter(row=>row.is_active)
  return {products:active.length,low:active.filter(row=>Number(row.stock_quantity)<=Number(row.low_stock_threshold)).length}
})
const selectedStock=computed(()=>products.value.find(row=>row.id===form.stock_item_id))
watch(()=>form.input_unit,()=>{form.unit_cost=''})
watch(()=>form.stock_item_id,()=>{form.unit_cost=''})
watch(()=>masterForm.opening_unit,()=>{masterForm.unit_cost=''})
const openingPreview=computed(()=>previewStockQuantity(masterForm.opening_quantity,masterForm.opening_unit,masterForm.units_per_package,{zero:true}))
const adjustPreview=computed(()=>previewStockQuantity(form.quantity,form.input_unit,selectedStock.value?.units_per_package||'1',{signed:form.movement_type==='adjust'}))
const quantityRule='最多三位小数，绝对值须小于 1000000000，换算结果也须符合此规则'
const masterValidation=computed(()=>{
  if(editingId.value&&editingCost.value!==null&&!masterForm.unit_cost.trim())return '已设置的库存成本不能清空，请填写有效金额'
  if(editingId.value&&masterForm.unit_cost.trim()&&!costPreview('1',masterForm.unit_cost,'1'))return '成本须为非负金额，最多两位小数'
  if(previewStockQuantity(masterForm.units_per_package,'base','1')==='—')return `每包装数量须大于零，${quantityRule}`
  if(!editingId.value&&masterForm.unit_cost.trim()&&!openingCost.value)return '成本须为非负金额、最多两位小数；有入库数量才能记成本'
  if(!editingId.value&&openingPreview.value==='—')return `期初数量须为非负数，${quantityRule}`
  if(!editingId.value&&masterForm.opening_unit==='package'&&!masterForm.package_unit.trim())return '请填写包装单位，或改用基本单位'
  return ''
})
const adjustValidation=computed(()=>{
  if(['purchase','opening'].includes(form.movement_type)&&form.unit_cost.trim()&&!receivingCost.value)return '成本须为非负金额，最多两位小数'
  if(adjustPreview.value==='—')return `变动数量须为有效非零数（仅盘点允许负数），${quantityRule}`
  if(form.input_unit==='package'&&selectedStock.value&&!selectedStock.value.package_unit)return '该库存没有包装单位，请使用基本单位'
  return ''
})
const movementNames:Record<string,string>={purchase:'采购入库',opening:'期初库存',return:'退货入库',loss:'报损',adjust:'盘点调整（增减量）',sale:'销售出库',void_return:'撤销返库'}
async function load(silent=false){
  const current=guardBusinessOperation('load');if(!current())return
  try{
    const [stock,history,used]=await Promise.all([http.get('/inventory/stock-items',{params:{include_inactive:includeInactive.value}}),http.get('/inventory/stock-movements',{params:historyId.value?{stock_item_id:historyId.value}:{}}),http.get('/inventory/usage')])
    if(!current())return
    products.value=apiData<StockItem[]>(stock);movements.value=apiData<StockMovement[]>(history);usage.value=apiData<StockUsage[]>(used)
  }catch(error){if(current()&&!silent)ElMessage.error(apiErrorMessage(error))}
}
function createNew(){
  if(!canCapability('inventory_write')||saving.value||authorizing.value)return
  editingId.value='';editingVersion.value=0
  Object.assign(masterForm,{name:'',category:'默认',base_unit:'',package_unit:'',units_per_package:'1',package_spec:'',low_stock_threshold:'0',opening_quantity:'0',opening_unit:'base',unit_cost:''})
  masterOpen.value=true
}
function edit(row:StockItem){
  if(!canCapability('inventory_write')||saving.value||authorizing.value)return
  editingId.value=row.id;editingVersion.value=row.version
  editingCost.value=row.unit_cost??null
  Object.assign(masterForm,{name:row.name,category:row.category,base_unit:row.base_unit,package_unit:row.package_unit,units_per_package:row.units_per_package,package_spec:row.package_spec,low_stock_threshold:row.low_stock_threshold,opening_quantity:'0',opening_unit:'base',unit_cost:row.unit_cost??''})
  masterOpen.value=true
}
function adjust(row?:StockItem){
  if(!canCapability('inventory_write')||saving.value||authorizing.value)return
  Object.assign(form,{stock_item_id:row?.id||'',version:row?.version||0,movement_type:'purchase',quantity:'1',input_unit:'base',reason:'采购入库',unit_cost:''});drawerOpen.value=true
}
watch(()=>form.stock_item_id,id=>{form.version=products.value.find(row=>row.id===id)?.version||0;form.input_unit='base'})
watch(()=>form.movement_type,kind=>{form.reason=receivingReasons[kind]?.[0]||'';form.unit_cost=''})
watch([includeInactive,historyId],()=>load())
async function write(scope:string,method:'post'|'patch'|'delete',url:string,body:Record<string,unknown>){
  if(!canCapability('inventory_write')||saving.value)return false
  const current=guardBusinessOperation('save');if(!current())return false
  const {password: _password,...safeBody}=body
  const {version,...intent}=safeBody,fingerprint=JSON.stringify(intent)
  if(pending.value&&(pending.value.scope!==scope||pending.value.fingerprint!==fingerprint)){ElMessage.warning('上一笔库存操作尚未确认，请先重试原操作');return false}
  const request=pending.value||{scope,fingerprint,body:{...body},key:pendingRequestKey(scope,JSON.stringify(safeBody)),method,url}
  pending.value=request;saving.value=true
  try{
    await http.request({method:request.method,url:request.url,data:request.body,headers:{'Idempotency-Key':request.key}})
    if(!current())return false
    clearPendingRequestKey(scope,request.key);pending.value=undefined;ElMessage.success('库存更新成功');return true
  }catch(error){
    if(!current())return false
    const status=(error as {response?:{status:number}}).response?.status
    if(status&&status>=400&&status<500){clearPendingRequestKey(scope,request.key);pending.value=undefined}
    ElMessage.error(apiErrorMessage(error));return false
  }finally{if(current())saving.value=false}
}
async function retryPending(){
  const request=pending.value
  if(request&&await write(request.scope,request.method,request.url,request.body)){masterOpen.value=false;drawerOpen.value=false;costOpen.value=false;await load()}
}
async function saveMaster(){
  if(saving.value||authorizing.value)return
  if(!masterForm.name.trim()||!masterForm.base_unit.trim())return ElMessage.warning('请填写库存名称和基本单位')
  if(masterValidation.value)return ElMessage.warning(masterValidation.value)
  const {opening_quantity,opening_unit,unit_cost}=masterForm
  const fields={name:masterForm.name.trim(),base_unit:masterForm.base_unit.trim(),package_unit:masterForm.package_unit.trim(),units_per_package:masterForm.units_per_package}
  const id=editingId.value
  const costChanged=!!id&&!!unit_cost.trim()&&(editingCost.value===null||Number(unit_cost)!==Number(editingCost.value))
  const body:Record<string,unknown>=id?{...fields,version:editingVersion.value,...(costChanged?{unit_cost:unit_cost.trim()}:{})}:{...fields,opening_unit,...(openingPreview.value!=='0.000'?{opening_quantity,...(unit_cost.trim()?{unit_cost:unit_cost.trim()}:{})}:{})}
  if(costChanged&&editingCost.value!==null){
    const current=guardBusinessOperation('authorizeMasterCost');authorizing.value=true
    try{
      const {value}=await ElMessageBox.prompt('修改已设置的库存成本，请输入本人登录密码。','修改库存成本',{inputType:'password',inputPattern:/\S+/,inputErrorMessage:'请输入本人登录密码',confirmButtonText:'确认修改',cancelButtonText:'取消'})
      if(!current()||!masterOpen.value||editingId.value!==id)return
      body.password=value
    }catch(error){if(current()&&error!=='cancel'&&error!=='close')ElMessage.error(apiErrorMessage(error));return}
    finally{authorizing.value=false}
  }
  if(await write(`stock:${id||'new'}:master`,id?'patch':'post',`/inventory/stock-items${id?'/'+id:''}`,body)){masterOpen.value=false;await load()}
}
async function save(){
  if(!selectedStock.value)return ElMessage.warning('请选择库存项目')
  if(!form.reason.trim())return ElMessage.warning('请填写调整原因或单据号')
  if(adjustValidation.value)return ElMessage.warning(adjustValidation.value)
  const {unit_cost,...fields}=form
  const body={...fields,reason:form.reason.trim(),...(['purchase','opening'].includes(form.movement_type)&&unit_cost.trim()?{unit_cost:unit_cost.trim()}:{})}
  if(await write(`stock:${form.stock_item_id}:adjust`,'post','/inventory/stock-adjust',body)){drawerOpen.value=false;await load()}
}
function editCost(row:StockMovement){if(saving.value||!canCapability('inventory_write'))return;costReceipt.value=row;costInput.value=row.cost?.unit_cost||'';costOpen.value=true}
async function saveCost(){
  const row=costReceipt.value;if(!row||!correctionCost.value||saving.value||authorizing.value)return
  const body:Record<string,unknown>={expected_cost_id:row.cost?.id||null,unit_cost:costInput.value.trim()}
  if(row.cost&&Number(row.cost.unit_cost)!==Number(body.unit_cost)){
    const current=guardBusinessOperation('authorizeReceiptCost');authorizing.value=true
    try{
      const {value}=await ElMessageBox.prompt('修改已设置的入库成本，请输入本人登录密码。','修改入库成本',{inputType:'password',inputPattern:/\S+/,inputErrorMessage:'请输入本人登录密码',confirmButtonText:'确认修改',cancelButtonText:'取消'})
      if(!current()||!costOpen.value||costReceipt.value?.id!==row.id)return
      body.password=value
    }catch(error){if(current()&&error!=='cancel'&&error!=='close')ElMessage.error(apiErrorMessage(error));return}
    finally{authorizing.value=false}
  }
  if(await write('stock:'+row.id+':cost','post','/inventory/stock-movements/'+row.id+'/cost',body)){costOpen.value=false;await load()}
}
async function archive(row:StockItem){
  if(!canCapability('inventory_write')||saving.value)return
  const current=guardBusinessOperation('archive'),body={version:row.version,confirm_writeoff:Number(row.stock_quantity)>0}
  try{await ElMessageBox.confirm(body.confirm_writeoff?`归档 ${row.name} 将报损剩余 ${row.stock_quantity} ${row.base_unit}，并保留流水。确定归档？`:`确定归档 ${row.name}？历史流水将保留。`,'归档库存',{type:'warning',confirmButtonText:'确认归档',cancelButtonText:'取消'})}catch{return}
  if(!current())return
  if(await write(`stock:${row.id}:archive`,'delete',`/inventory/stock-items/${row.id}`,body))await load()
}
onMounted(()=>{load();unsubscribeRealtime=subscribeRealtime(['inventory','catalog'],()=>load(true))})
onBeforeUnmount(()=>unsubscribeRealtime?.())
</script>
<template>
  <div>
    <AppPageHeader title="库存管理" description="整箱入库，按袋、瓶等实际单位耗用。" eyebrow="INVENTORY"><template #actions>
      <el-button v-if="canCapability('inventory_write')&&pending" data-testid="stock-retry" :loading="saving" type="warning" @click="retryPending">重试待确认操作</el-button>
      <el-button v-if="canCapability('inventory_write')" @click="adjust()">入库 / 调整</el-button>
      <el-button v-if="canCapability('inventory_write')" data-testid="stock-new" type="primary" @click="createNew">新增库存</el-button>
    </template></AppPageHeader>
    <section class="inventory-summary"><article><span>库存项目</span><strong>{{summary.products}}</strong><small>种</small></article><article :class="{warning:summary.low}"><span>低库存</span><strong>{{summary.low}}</strong><small>种需要关注</small></article></section>
    <div class="inventory-toolbar"><el-input v-model="keyword" clearable placeholder="搜索库存项目"/><el-checkbox v-if="canCapability('inventory_write')" v-model="includeInactive">包含已归档</el-checkbox><span>每页10条 · 共{{filtered.length}}条</span></div>
    <el-card shadow="never"><template #header><div class="history-header"><strong>库存项目</strong><el-pagination v-model:current-page="page" :page-size="10" :total="filtered.length" layout="total, prev, pager, next" background class="stock-pagination"/></div></template><el-table :data="paged" row-key="id">
      <el-table-column prop="name" label="库存项目" min-width="160"/>
      <el-table-column label="现存数量" min-width="160"><template #default="scope"><strong>{{scope.row.stock_quantity}} {{scope.row.base_unit}}</strong></template></el-table-column>
      <el-table-column label="入库包装" min-width="150"><template #default="scope">{{scope.row.package_unit?'1 '+scope.row.package_unit+' = '+scope.row.units_per_package+' '+scope.row.base_unit:'按基本单位入库'}}</template></el-table-column>
      <el-table-column label="成本单价" min-width="130"><template #default="scope">{{scope.row.unit_cost==null?'未设置':'¥'+scope.row.unit_cost+'/'+scope.row.base_unit}}</template></el-table-column>
      <el-table-column label="预警 / 状态" min-width="165"><template #default="scope"><span class="alert-quantity">{{scope.row.low_stock_threshold}} {{scope.row.base_unit}}</span><el-tag :type="!scope.row.is_active?'info':Number(scope.row.stock_quantity)<=Number(scope.row.low_stock_threshold)?'danger':'success'">{{!scope.row.is_active?'已归档':Number(scope.row.stock_quantity)<=Number(scope.row.low_stock_threshold)?'库存偏低':'充足'}}</el-tag></template></el-table-column>
      <el-table-column label="操作" width="290" fixed="right"><template #default="scope"><div class="stock-actions"><template v-if="canCapability('inventory_write')&&scope.row.is_active"><el-button data-testid="stock-adjust" size="small" type="primary" plain :disabled="saving" @click="adjust(scope.row)">入库</el-button><el-button data-testid="stock-edit" size="small" :disabled="saving" @click="edit(scope.row)">编辑</el-button></template><el-button size="small" @click="historyId=scope.row.id">流水</el-button><el-button v-if="canCapability('inventory_write')&&scope.row.is_active" class="archive-action" data-testid="stock-archive" link type="danger" :disabled="saving" @click="archive(scope.row)">归档</el-button></div></template></el-table-column>
    </el-table></el-card>
    <section class="stock-details">
      <el-card shadow="never"><template #header>各销售项目最常用耗材</template><el-table :data="usage.filter(row=>row.is_most_used)" max-height="420"><el-table-column prop="catalog_name" label="销售项目"/><el-table-column prop="stock_name" label="耗材"/><el-table-column prop="usage_count" label="次数" width="70"/></el-table><p class="muted">按有效订单统计，并列保留；不自动绑定耗材。</p></el-card>
      <el-card shadow="never"><template #header><div class="history-header"><strong>库存流水</strong><el-button v-if="historyId" link @click="historyId=''">查看全部</el-button></div></template>
        <el-timeline class="movement-list"><el-timeline-item v-for="row in movements" :key="row.id" :timestamp="formatBusinessTime(row.created_at)"><div class="movement"><strong>{{products.find(master=>master.id===row.stock_item_id)?.name||row.stock_item_id}} · {{movementNames[row.movement_type]||row.movement_type}}</strong><b>{{Number(row.quantity)>=0?'+':''}}{{row.quantity}} {{row.base_unit}}</b><span>结存 {{row.balance_after}} {{row.base_unit}} · {{row.reason}} · 输入 {{row.input_quantity}} {{row.input_unit==='package'?row.package_unit:row.base_unit}} × {{row.conversion_factor}}</span><template v-if="['purchase','opening'].includes(row.movement_type)"><span v-if="row.cost">成本 ¥{{row.cost.total_cost}} · ¥{{row.cost.unit_cost}}/{{row.input_unit==='package'?row.package_unit:row.base_unit}} · ¥{{row.cost.base_unit_cost}}/{{row.base_unit}}</span><span v-else>成本未设置</span><el-button v-if="canCapability('inventory_write')" link type="primary" :disabled="saving" @click="editCost(row)">{{row.cost?'修改成本':'补录成本'}}</el-button></template></div></el-timeline-item></el-timeline><el-empty v-if="!movements.length" description="暂无库存流水"/>
      </el-card>
    </section>
    <el-drawer v-model="masterOpen" :title="editingId?'编辑库存':'新增库存'" size="520px" :close-on-click-modal="!saving && !authorizing" :close-on-press-escape="!saving && !authorizing" :show-close="!saving && !authorizing">
      <el-alert v-if="masterValidation" data-testid="stock-validation" :title="masterValidation" type="warning" :closable="false"/>
      <el-form label-position="top" :disabled="saving || authorizing"><el-form-item label="库存名称"><el-input v-model="masterForm.name"/></el-form-item><el-form-item label="基本单位（例如袋、瓶）"><el-input v-model="masterForm.base_unit" :disabled="!!editingId"/></el-form-item><el-form-item label="入库包装单位（选填）"><el-input v-model="masterForm.package_unit" placeholder="箱、包"/></el-form-item><el-form-item label="每包装基本单位数"><el-input v-model="masterForm.units_per_package" inputmode="decimal"/></el-form-item>
        <template v-if="!editingId"><el-form-item label="期初数量（0表示暂不入库）"><el-input v-model="masterForm.opening_quantity" inputmode="decimal"/></el-form-item><el-form-item label="期初输入单位"><el-select v-model="masterForm.opening_unit"><el-option :label="masterForm.base_unit||'基本单位'" value="base"/><el-option v-if="masterForm.package_unit" :label="masterForm.package_unit" value="package"/></el-select></el-form-item><div class="receiving-preview"><p data-testid="opening-preview">换算结存 {{openingPreview}} {{masterForm.base_unit}}</p><p>自动预警 {{warningPreview(openingPreview)}} {{masterForm.base_unit}}（入库量15%）</p></div><el-form-item :label="'成本单价（元/'+(masterForm.opening_unit==='package'?masterForm.package_unit:masterForm.base_unit)+'，可后补）'"><el-input v-model="masterForm.unit_cost" inputmode="decimal" placeholder="未设置"/></el-form-item><p data-testid="opening-cost-preview"><template v-if="openingCost">总成本 ¥{{openingCost.total}} · 基本单位成本 ¥{{openingCost.baseUnit}}</template><template v-else>成本未设置，不按0元统计</template></p></template>
        <template v-else><el-form-item :label="'库存成本单价（元/'+masterForm.base_unit+'）'"><el-input data-testid="master-unit-cost" v-model="masterForm.unit_cost" inputmode="decimal" placeholder="未设置" :disabled="authorizing"/></el-form-item><p class="muted">库存成本按基本单位设置；修改已有成本需本人登录密码。历史入库成本独立保留。预警由每次采购入库量自动计算。</p></template>
      </el-form><template #footer><el-button :disabled="saving || authorizing" @click="masterOpen=false">取消</el-button><el-button data-testid="stock-save" type="primary" :loading="saving || authorizing" :disabled="saving || authorizing" @click="saveMaster">保存库存</el-button></template>
    </el-drawer>
    <el-drawer v-model="drawerOpen" title="库存入库 / 调整" size="500px" :close-on-click-modal="!saving" :close-on-press-escape="!saving">
      <el-alert v-if="adjustValidation" data-testid="adjust-validation" :title="adjustValidation" type="warning" :closable="false"/>
      <el-form label-position="top" :disabled="saving"><el-form-item label="库存项目"><el-select v-model="form.stock_item_id" filterable class="full-width"><el-option v-for="row in products.filter(row=>row.is_active)" :key="row.id" :label="row.name+'（'+row.stock_quantity+' '+row.base_unit+'）'" :value="row.id"/></el-select></el-form-item><el-form-item label="操作类型"><el-select v-model="form.movement_type"><el-option v-for="kind in ['purchase','opening','return','loss','adjust']" :key="kind" :label="movementNames[kind]" :value="kind"/></el-select></el-form-item><el-form-item label="变动数量（盘点减少填负数）"><el-input v-model="form.quantity" inputmode="decimal"/></el-form-item><el-form-item label="输入单位"><el-select v-model="form.input_unit"><el-option :label="selectedStock?.base_unit||'基本单位'" value="base"/><el-option v-if="selectedStock?.package_unit" :label="selectedStock.package_unit" value="package"/></el-select></el-form-item><div class="receiving-preview"><p data-testid="adjust-preview">换算变动 {{adjustPreview==='—'?'—':form.movement_type==='loss'?'-'+adjustPreview:adjustPreview}} {{selectedStock?.base_unit}}</p><p v-if="['purchase','opening'].includes(form.movement_type)">自动预警 {{warningPreview(adjustPreview)}} {{selectedStock?.base_unit}}（本次入库量15%）</p></div><el-form-item label="原因"><el-select v-model="form.reason"><el-option v-for="reason in receivingReasons[form.movement_type]||[]" :key="reason" :label="reason" :value="reason"/></el-select></el-form-item><template v-if="['purchase','opening'].includes(form.movement_type)"><el-form-item :label="'成本单价（元/'+(form.input_unit==='package'?selectedStock?.package_unit:selectedStock?.base_unit)+'，可后补）'"><el-input v-model="form.unit_cost" inputmode="decimal" placeholder="未设置"/></el-form-item><p v-if="receivingCost">总成本 ¥{{receivingCost.total}} · 基本单位成本 ¥{{receivingCost.baseUnit}}</p><p v-else>成本未设置，不按0元统计</p></template></el-form><template #footer><el-button :disabled="saving" @click="drawerOpen=false">取消</el-button><el-button data-testid="adjust-save" type="primary" :loading="saving" @click="save">确认更新</el-button></template>
    </el-drawer>
    <el-dialog v-model="costOpen" title="补录 / 修改入库成本" width="440px" :close-on-click-modal="!saving" :close-on-press-escape="!saving"><p>本笔入库 {{costReceipt?.input_quantity}} {{costReceipt?.input_unit==='package'?costReceipt?.package_unit:costReceipt?.base_unit}}，历史数量及换算保持不变。</p><el-form label-position="top"><el-form-item :label="'单价（元/'+(costReceipt?.input_unit==='package'?costReceipt?.package_unit:costReceipt?.base_unit)+'）'"><el-input v-model="costInput" :disabled="saving" inputmode="decimal"/></el-form-item></el-form><p v-if="correctionCost">总成本 ¥{{correctionCost.total}} · 每基本单位 ¥{{correctionCost.baseUnit}}</p><p v-else>请输入有效成本金额</p><p class="muted">补录和修改保留操作人、时间及前后金额。</p><template #footer><el-button :disabled="saving" @click="costOpen=false">取消</el-button><el-button type="primary" :loading="saving" :disabled="!correctionCost" @click="saveCost">保存成本</el-button></template></el-dialog>
  </div>
</template>
<style scoped>
.inventory-summary{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-bottom:16px}.inventory-summary article{padding:16px 20px;border:1px solid var(--xq-border);border-radius:8px;background:white}.inventory-summary span,.inventory-summary strong,.inventory-summary small{display:block}.inventory-summary span,.inventory-summary small,.muted{color:var(--xq-text-3)}.inventory-summary strong{margin:5px 0;font-size:26px}.inventory-summary .warning strong{color:var(--xq-danger)}.inventory-toolbar{display:flex;align-items:center;gap:16px;margin-bottom:14px;flex-wrap:wrap}.inventory-toolbar .el-input{max-width:300px}.inventory-toolbar>span{margin-left:auto;color:var(--xq-text-3);font-size:12px}.stock-actions{display:flex;align-items:center;gap:7px;white-space:nowrap}.stock-actions .el-button+.el-button{margin-left:0}.stock-actions .archive-action{margin-left:8px;padding-left:12px;border-left:1px solid var(--xq-border)}.alert-quantity{display:block;margin-bottom:5px;color:var(--xq-text-2);font-size:12px}.stock-pagination{justify-content:flex-end;margin-top:18px}.stock-details{display:grid;grid-template-columns:1fr 1.4fr;gap:18px;margin-top:18px}.history-header{display:flex;justify-content:space-between;align-items:center}.movement-list{max-height:420px;overflow:auto;padding:6px 8px 0 12px}.movement{display:grid;grid-template-columns:1fr auto;gap:6px 10px}.movement span{grid-column:1/-1;color:var(--xq-text-3);font-size:12px}.movement .el-button{justify-self:start}.receiving-preview{padding:8px 14px;margin-bottom:18px;background:#f3f7f5;border-radius:6px}.receiving-preview p{margin:6px 0}.el-form :deep(.el-select){width:100%}@media(max-width:1100px){.stock-details{grid-template-columns:1fr}}
.history-header>.stock-pagination{margin-top:0}
</style>
