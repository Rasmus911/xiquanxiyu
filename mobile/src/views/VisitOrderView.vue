<script setup lang="ts">
import { canAccess, useBusinessGuard } from '../business/state'
const guardBusinessOperation = useBusinessGuard()

import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { dataOf, errorMessage, http } from '../api'
import MobileState from '../components/common/MobileState.vue'
import MobileTopbar from '../components/navigation/MobileTopbar.vue'
import CatalogTabs from '../components/orders/CatalogTabs.vue'
import MobileCatalogPicker from '../components/orders/MobileCatalogPicker.vue'
import OrderSummaryBar from '../components/orders/OrderSummaryBar.vue'
import ConsumptionEditor from '../components/orders/ConsumptionEditor.vue'
import { validQuantity } from '../domain/inventory/quantity'
import { changeProductQuantity, selectionTotals, selectedOrderRows, toggleServiceQuantity } from '../order-selection'
import { togglePackageSelection } from '../order-package'
import { pendingOperationKey, clearPendingOperationKey } from '../idempotency'
import { useBusinessStore } from '../stores/business'
import { useConnectivityStore } from '../stores/connectivity'
import type { Consumption, MobileCatalogItem } from '../types'
import { ref } from 'vue'
const layoutEditing = ref(false)
const pending = computed(() => business.pendingOrder(visitId.value))
const route=useRoute();const router=useRouter();const business=useBusinessStore();const connectivity=useConnectivityStore();const kind=ref<'all'|'service'|'product'>('all');const message=ref('');const now=ref(Date.now());let timer=0
const visitId=computed(()=>String(route.params.visitId));const band=computed(()=>business.wristbands.find(row=>row.visit_id===visitId.value));const rows=computed(()=>selectedOrderRows(business.catalog,business.quantities));const totals=computed(()=>selectionTotals(rows.value));const kinds=computed(()=>totals.value.kinds);const units=computed(()=>totals.value.units);const amount=computed(()=>totals.value.amount);const elapsed=computed(()=>{if(!band.value)return'';const seconds=Math.max(0,Math.floor((now.value-new Date(band.value.opened_at).getTime())/1000));return`${String(Math.floor(seconds/3600)).padStart(2,'0')}:${String(Math.floor(seconds%3600/60)).padStart(2,'0')}`})
const consumptionDraft=ref<{visitId:string;number:string;version?:number;rows:ReturnType<typeof selectedOrderRows>;materials:Record<string,Consumption[]>;replacing:boolean}|null>(null)
function openConsumption(){
  if(!rows.value.length||pending.value||!band.value||!connectivity.canWrite||business.sending||layoutEditing.value||!canAccess('mobile:order'))return
  const chosenPackage=rows.value.find(row=>row.kind==='package')
  consumptionDraft.value={visitId:visitId.value,number:band.value.number,version:band.value.version,
    rows:rows.value.map(row=>({...row})),materials:JSON.parse(JSON.stringify(business.materials)),
    replacing:!!(chosenPackage&&band.value.package_catalog_item_id&&chosenPackage.id!==band.value.package_catalog_item_id)}
  message.value=''
}
function select(item:MobileCatalogItem){
  if(item.kind==='package') {
    if(canAccess('visit:package')) business.quantities=togglePackageSelection(business.quantities,business.catalog,item.id)
  } else if(item.kind==='service')business.quantities=toggleServiceQuantity(business.quantities,item.id)
  else business.quantities=changeProductQuantity(business.quantities,item,1)
}
function change(item:MobileCatalogItem,delta:number){if(item.kind==='product')business.quantities=changeProductQuantity(business.quantities,item,delta)}
async function submit(retry = false){
  const draft=consumptionDraft.value
  if ((!retry && (!draft || draft.visitId!==visitId.value || !band.value || pending.value)) || !connectivity.canWrite || business.sending || layoutEditing.value || !canAccess('mobile:order')) return
  const isCurrent = guardBusinessOperation('submit')
  if (!isCurrent()) return
  let target: ReturnType<typeof business.prepareOrder>
  const chosenPackage=retry ? undefined : draft!.rows.find(row=>row.kind==='package')
  const replacing=!retry&&draft!.replacing
  if(replacing && !window.confirm(`更换为${chosenPackage!.name}？当前手牌未结账的包含项目将重新计费。`)) return
  try {
    if (retry) {
      const original = business.pendingOrder(visitId.value)
      if (!original) return
      target = original
    } else {
      const items = draft!.rows.map(row => {
        const selection = draft!.materials[row.id]
        if (!selection) throw new Error(`请为${row.name}选择耗材或明确不消耗库存`)
        if (selection.some(item => !validQuantity(item.quantity))) throw new Error('耗用数量须为正数，最多三位小数')
        return { catalog_item_id: row.id, quantity: String(row.quantity), inventory_mode: 'manual' as const, inventory_consumption: selection }
      })
      target = business.prepareOrder(draft!.visitId, draft!.version, items,replacing)
      consumptionDraft.value=null
    }
  }
  catch (cause) { message.value = errorMessage(cause); return }
  const releaseBusy = business.beginBusinessOperation('order')
  message.value = ''
  try {
    if (!retry && (!connectivity.lastSyncAt || Date.now() - connectivity.lastSyncAt > 30000)) {
      await business.refreshBootstrap(true); if (!isCurrent()) return
      if (!business.wristbands.some(row => row.visit_id === target.visitId)) {
        message.value = '该手牌已结账或停用'
        await router.replace('/orders'); return
      }
    }
    dataOf(await http.post(`/mobile/visits/${target.visitId}/items`, { items: target.items, version: target.version,
      ...(target.confirmReplace ? {confirm_replace:true} : {}) }, { headers: { 'Idempotency-Key': target.key } }))
    if (!isCurrent()) return
    business.completeOrder(target.visitId); if(visitId.value===target.visitId) message.value = '加单成功'
    await business.refreshBootstrap(true)
  } catch (cause) { if (isCurrent()) {
    business.rejectOrder(target.visitId, (cause as { response?: { status: number } })?.response?.status)
    if(visitId.value===target.visitId) message.value = errorMessage(cause)
  } }
  finally { releaseBusy() }
}

async function cancelPackage(){
  if(!band.value?.package_catalog_item_id || pending.value || !canAccess('visit:package') || !connectivity.canWrite || business.sending || layoutEditing.value) return
  const target={id:visitId.value,version:band.value.version}
  if(!window.confirm('取消套票后，现有包含项目恢复单项收费，已售商品库存不变。确定取消吗？')) return
  const isCurrent=guardBusinessOperation('cancelPackage'); if(!isCurrent()) return
  const scope=`package-cancel:${target.id}`
  const key=pendingOperationKey(scope,String(target.version))
  const releaseBusy=business.beginBusinessOperation('order')
  try {
    dataOf(await http.delete(`/mobile/visits/${target.id}/package`,{data:{version:target.version,idempotency_key:key}}))
    if(!isCurrent()) return
    clearPendingOperationKey(scope)
    if(visitId.value===target.id) message.value='套票已取消'
    await business.refreshBootstrap(true)
  } catch(cause) {
    if(!isCurrent()) return
    const status=(cause as {response?:{status:number}}).response?.status
    if(status && status>=400 && status<500) clearPendingOperationKey(scope)
    if(visitId.value===target.id) message.value=errorMessage(cause)
  } finally {releaseBusy()}
}

function back(event:Event){if(consumptionDraft.value){event.preventDefault();if(!business.sending)consumptionDraft.value=null}}
watch(visitId, id => { consumptionDraft.value=null;business.selectVisit(id); message.value = '' }, { immediate: true,flush:'sync' })
watch(()=>canAccess('mobile:order'),allowed=>{if(!allowed)consumptionDraft.value=null})
onMounted(()=>{document.addEventListener('xiquan:back-request',back);timer=window.setInterval(()=>now.value=Date.now(),30000);const current=guardBusinessOperation('consumables');if(canAccess('mobile:order'))void business.loadConsumables().catch(cause=>{if(current())message.value=errorMessage(cause)})});onBeforeUnmount(()=>{document.removeEventListener('xiquan:back-request',back);window.clearInterval(timer)})
</script>
<template>
  <div><MobileTopbar :title="band?`${band.number} 号手牌`:'手牌点单'" :subtitle="band?`${band.bath_area==='male'?'男浴':'女浴'} · ${elapsed} · 当前消费 ¥${band.amount}`:''" back @back="router.replace('/orders')"/>
    <main class="mobile-page order-page">
      <div v-if="message" class="notice">{{message}}</div>
      <section v-if="pending" class="notice">
        <strong>上一笔加单结果尚未确认</strong>
        <p v-for="line in pending.items" :key="line.catalog_item_id">{{business.catalog.find(row=>row.id===line.catalog_item_id)?.name || line.catalog_item_id}} × {{line.quantity}} · {{line.inventory_consumption?.length ? line.inventory_consumption.map(row=>`${business.consumables.find(stock=>stock.id===row.stock_item_id)?.name || row.stock_item_id} ${row.quantity}`).join('、') : '不消耗库存'}}</p>
        <button data-testid="retry-order" :disabled="business.sending||!connectivity.canWrite" @click="submit(true)">重试原加单</button><p>原请求确认后可提交新的选择。</p>
      </section>
      <MobileState v-if="!band" kind="empty" title="该手牌已不在使用中" description="可能已经结账，请返回刷新"/>
      <template v-else>
        <div class="quick-order-header" data-testid="quick-order-header"><strong>快速加单</strong><OrderSummaryBar compact :kinds="kinds" :units="units" :amount="amount" :sending="business.sending" :disabled="layoutEditing||!units||!connectivity.canWrite||business.sending||!!pending||!!consumptionDraft" @submit="openConsumption"/></div>
        <div v-if="band.package_catalog_item_id" class="notice">当前已选套票 · 账单金额以服务器为准 <button v-if="canAccess('visit:package')" :disabled="business.sending||layoutEditing||!connectivity.canWrite||!!pending" @click="cancelPackage">取消套票</button></div>
        <CatalogTabs v-if="!layoutEditing" v-model="kind"/>
        <MobileCatalogPicker :items="business.catalog" :quantities="business.quantities" :kind="kind" :can-arrange="canAccess('catalog:layout')&&!business.sending&&!pending" @select="select" @change="change" @editing-change="layoutEditing=$event" @arranged="business.refreshBootstrap(true)"/>
      </template>
    </main>
    <div v-if="consumptionDraft" class="sheet-mask"><section class="consumption-sheet" role="dialog" aria-modal="true" aria-labelledby="consumption-title">
      <h3 id="consumption-title">{{consumptionDraft.number}} 号手牌 · 确认耗材</h3><p>逐项选择耗材或明确无耗材，然后确认加单。</p><div v-if="message" class="notice" role="alert">{{message}}</div>
      <div v-for="row in consumptionDraft.rows" :key="row.id"><p>{{row.name}} × {{row.quantity}}</p><ConsumptionEditor :item-id="row.id" :name="row.name" :stocks="business.consumables" :model-value="consumptionDraft.materials[row.id]" :disabled="business.sending" @update:model-value="value=>{if(!consumptionDraft)return;if(value===undefined)delete consumptionDraft.materials[row.id];else consumptionDraft.materials[row.id]=value}"/></div>
      <div class="sheet-actions"><button data-testid="confirm-consumption" :disabled="business.sending||!connectivity.canWrite" @click="submit()">确认加单</button><button data-testid="cancel-consumption" :disabled="business.sending" @click="consumptionDraft=null">取消</button></div>
    </section></div>
  </div>
</template>
<style scoped>.order-page{padding-bottom:90px}.quick-order-header{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:14px}.sheet-mask{position:fixed;inset:0;z-index:70;display:flex;align-items:end;background:#10203577}.consumption-sheet{width:100%;max-height:88vh;overflow:auto;padding:18px;padding-bottom:calc(18px + env(safe-area-inset-bottom));background:white;border-radius:22px 22px 0 0}.consumption-sheet>p{font-size:13px;color:var(--m-text-3)}.sheet-actions{display:flex;gap:10px;position:sticky;bottom:0;background:white;padding-top:12px}.sheet-actions button{min-height:46px;flex:1;border:1px solid var(--m-border);border-radius:7px;background:white;color:var(--m-primary)}.sheet-actions button:first-child{background:var(--m-primary);color:white}.sheet-actions button:disabled{opacity:.45}</style>
