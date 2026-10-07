<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import type { StockItem } from '../../types'
import { previewStockQuantity, stockConversionError } from '../../domain/inventory/quantity'
import { costPreview, warningPreview, receivingReasons } from '../../domain/inventory/receiving'
const props=defineProps<{item:StockItem|null;saving:boolean}>()
const emit=defineEmits<{close:[];save:[value:{quantity:string;input_unit:string;reason:string;movement_type:string;unit_cost?:string}]}>()
const form=reactive({quantity:'1',input_unit:'base',reason:'采购入库',movement_type:'purchase',unit_cost:''})
watch(()=>props.item,()=>{Object.assign(form,{quantity:'1',input_unit:'base',reason:'采购入库',movement_type:'purchase',unit_cost:''})})
watch(()=>form.input_unit,()=>{form.unit_cost=''})
watch(()=>form.movement_type,kind=>{form.reason=receivingReasons[kind]?.[0]||'采购入库';form.unit_cost=''})
const cost=computed(()=>costPreview(form.quantity,form.unit_cost,form.input_unit==='package'?props.item?.units_per_package||'1':'1'))
const preview=computed(()=>previewStockQuantity(form.quantity,form.input_unit,props.item?.units_per_package || '1'))
const conversionError=computed(()=>stockConversionError(form.quantity,form.input_unit,props.item?.units_per_package || '1'))
const error=computed(()=>conversionError.value || (form.unit_cost.trim()&&!cost.value?'成本须为非负金额，最多两位小数':''))
function save(){if(!props.saving&&props.item&&!error.value)emit('save',{quantity:form.quantity,input_unit:form.input_unit,reason:form.reason,movement_type:form.movement_type,...(form.unit_cost.trim()?{unit_cost:form.unit_cost.trim()}:{})})}
</script>
<template>
  <div v-if="item" class="sheet-mask" @click.self="!saving && $emit('close')"><section class="sheet">
    <h3>{{item.name}} 采购入库</h3><p>当前 {{item.stock_quantity}} {{item.base_unit}} · {{item.package_spec}}</p>
    <label>入库数量<input v-model="form.quantity" inputmode="decimal" :disabled="saving" /></label>
    <label>输入单位<select v-model="form.input_unit" :disabled="saving"><option value="base">{{item.base_unit}}</option><option v-if="item.package_unit" value="package">{{item.package_unit}}</option></select></label>
    <p>折算入库：{{preview}} {{item.base_unit}}</p>
    <label>入库类型<select v-model="form.movement_type" :disabled="saving"><option value="purchase">采购入库</option><option value="return">误出库 / 退回</option></select></label>
    <label>原因<select v-model="form.reason" :disabled="saving"><option v-for="reason in receivingReasons[form.movement_type]" :key="reason">{{reason}}</option></select></label>
    <template v-if="form.movement_type==='purchase'"><p>预警 {{warningPreview(preview)}} {{item.base_unit}}（本次入库15%）</p><label>成本单价（元/{{form.input_unit==='package'?item.package_unit:item.base_unit}}，可后补）<input v-model="form.unit_cost" name="unit_cost" inputmode="decimal" :disabled="saving" placeholder="未设置"/></label><p v-if="cost">总成本 ¥{{cost.total}} · 每{{item.base_unit}} ¥{{cost.baseUnit}}</p><p v-else>未设置成本，不按0元统计</p></template>
    <p v-if="error" role="alert">{{error}}</p>
    <button class="primary-button" :disabled="saving||!!error" @click="save">{{saving?'正在提交':'确认入库'}}</button>
    <button :disabled="saving" @click="$emit('close')">取消</button>
  </section></div>
</template>
<style scoped>.sheet-mask{position:fixed;z-index:70;inset:0;display:flex;align-items:end;background:rgba(10,20,35,.46)}.sheet{width:100%;max-height:85vh;overflow:auto;padding:18px;border-radius:24px 24px 0 0;background:white}.sheet label{display:grid;gap:6px;margin:12px 0}.sheet input,.sheet select,.sheet button{min-height:46px;padding:8px 12px;border:1px solid var(--m-border);border-radius:8px}.sheet button{width:100%;margin-top:8px}.primary-button{color:white;background:var(--m-primary)}</style>
