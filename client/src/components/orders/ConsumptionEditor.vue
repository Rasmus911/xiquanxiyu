<script setup lang="ts">
import type { CatalogItem, Consumable, ManualConsumption } from '../../types'
const props = defineProps<{ items: CatalogItem[]; quantities: Record<string, number>; stock: Consumable[]; modelValue: Record<string, ManualConsumption[] | undefined>; disabled?: boolean; target: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: Record<string, ManualConsumption[] | undefined>] }>()
function replace(id: string, rows: ManualConsumption[] | undefined) { emit('update:modelValue', { ...props.modelValue, [id]: rows }) }
function update(id: string, index: number, field: keyof ManualConsumption, value: string) {
  replace(id, (props.modelValue[id] || []).map((row, i) => i === index ? { ...row, [field]: value } : row))
}
</script>
<template>
  <div v-if="Object.keys(quantities).length" class="consumption-editor">
    <strong>耗材选择 · 加至 {{ target }} 号手牌</strong>
    <p class="muted">填写每行全部销售数量所需的耗材总量（基本单位）；可用库存供参考，提交时由服务器核对。</p>
    <fieldset v-for="item in items.filter(row => quantities[row.id])" :key="item.id" :disabled="disabled">
      <legend>{{ item.name }} × {{ quantities[item.id] }}</legend>
      <label><input :data-testid="`no-consumption-${item.id}`" type="checkbox" :checked="modelValue[item.id]?.length === 0" @change="replace(item.id, ($event.target as HTMLInputElement).checked ? [] : undefined)" /> 本行无耗材</label>
      <div v-for="(row,index) in modelValue[item.id] || []" :key="index" class="consumption-row">
        <select :data-testid="`consumption-stock-${item.id}-${index}`" :value="row.stock_item_id" aria-label="选择耗材" @change="update(item.id,index,'stock_item_id',($event.target as HTMLSelectElement).value)">
          <option value="">请选择耗材</option><option v-for="master in stock" :key="master.id" :value="master.id">{{ master.name }} · 可用 {{ master.stock_quantity }} {{ master.base_unit }} · {{ master.package_spec }}</option>
        </select>
        <input :data-testid="`consumption-quantity-${item.id}-${index}`" :value="row.quantity" type="text" inputmode="decimal" aria-label="本行耗材总量" placeholder="本行总量" @input="update(item.id,index,'quantity',($event.target as HTMLInputElement).value)" />
        <span>{{ stock.find(master => master.id === row.stock_item_id)?.base_unit }}</span>
        <el-button size="small" @click="replace(item.id, modelValue[item.id]!.length > 1 ? modelValue[item.id]!.filter((_,i)=>i!==index) : undefined)">移除</el-button>
      </div>
      <el-button :data-testid="`add-consumption-${item.id}`" size="small" @click="replace(item.id,[...(modelValue[item.id] || []),{stock_item_id:'',quantity:'1'}])">添加耗材</el-button>
      <span v-if="modelValue[item.id] === undefined" class="muted"> 请选耗材或明确勾选无耗材</span>
    </fieldset>
  </div>
</template>
<style scoped>
.consumption-editor{margin-top:16px}fieldset{border:1px solid var(--xq-border);border-radius:8px;margin:10px 0;padding:12px}legend{padding:0 6px}.consumption-row{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0}.consumption-row select{flex:1;min-width:180px}.consumption-row input{width:90px}select,input[type=text]{border:1px solid var(--xq-border);border-radius:4px;padding:6px}
</style>
