<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Consumable, Consumption } from '../../types'
const props=defineProps<{itemId:string;name:string;stocks:Consumable[];modelValue:Consumption[]|undefined;disabled?:boolean}>()
const emit=defineEmits<{ 'update:modelValue':[value:Consumption[]|undefined] }>()
const search=ref('');const selected=ref('')
const available=computed(()=>props.stocks.filter(row=>!props.modelValue?.some(c=>c.stock_item_id===row.id) && `${row.name}${row.category}`.includes(search.value.trim())))
function add(){if(!selected.value)return;emit('update:modelValue',[...(props.modelValue||[]),{stock_item_id:selected.value,quantity:'1'}]);selected.value=''}
function setQuantity(index:number,value:string){emit('update:modelValue',props.modelValue?.map((row,i)=>i===index?{...row,quantity:value}:row))}
function remove(id:string){const rows=props.modelValue?.filter(row=>row.stock_item_id!==id);emit('update:modelValue',rows?.length?rows:undefined)}
function stock(id:string){return props.stocks.find(row=>row.id===id)}
</script>
<template>
  <section class="mobile-card materials" :data-testid="`consumption-${itemId}`">
    <strong>{{name}} · 消耗库存</strong><p>填写这条订单的总耗用量（基本单位），不乘销售数量。现存量仅供参考。</p>
    <label><input type="checkbox" :data-testid="`no-consumption-${itemId}`" :checked="modelValue?.length===0" :disabled="disabled" @change="emit('update:modelValue',($event.target as HTMLInputElement).checked?[]:undefined)"/> 本项不消耗库存</label>
    <div v-for="(row,index) in modelValue" :key="row.stock_item_id" class="material-row">
      <span>{{stock(row.stock_item_id)?.name || row.stock_item_id}} · {{stock(row.stock_item_id)?.base_unit}}</span>
      <input :value="row.quantity" inputmode="decimal" :data-testid="`stock-quantity-${itemId}-${row.stock_item_id}`" :aria-label="`${stock(row.stock_item_id)?.name}总耗用量`" :disabled="disabled" @input="setQuantity(index,($event.target as HTMLInputElement).value)"/>
      <button :disabled="disabled" @click="remove(row.stock_item_id)">移除</button>
    </div>
    <input v-model="search" class="mobile-input" placeholder="搜索库存" :disabled="disabled"/>
    <select v-model="selected" :data-testid="`stock-select-${itemId}`" :disabled="disabled"><option value="">选择库存</option><option v-for="row in available" :key="row.id" :value="row.id">{{row.name}} · 余 {{row.stock_quantity}} {{row.base_unit}} · {{row.package_spec}}</option></select>
    <button :disabled="disabled||!selected" :data-testid="`stock-add-${itemId}`" @click="add">添加耗材</button>
  </section>
</template>
<style scoped>.materials{margin-top:12px;padding:12px}.materials p{font-size:12px;color:var(--m-text-3)}.materials select{width:100%;min-height:44px;margin:8px 0}.material-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:8px}.material-row input{width:85px;min-height:42px}.materials button{min-height:40px;padding:8px}</style>
