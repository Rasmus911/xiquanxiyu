<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Check } from '@element-plus/icons-vue'
import { visibleCatalog, type CatalogFilterKind } from '../../domain/catalog/filter'
import { useCatalogLayout } from '../../composables/useCatalogLayout'
import { useCatalogPointer } from '../../composables/useCatalogPointer'
import type { CatalogItem } from '../../types'

const props = defineProps<{ items: CatalogItem[]; quantities: Record<string, number>; canArrange?: boolean; manualInventory?: boolean; disabled?: boolean }>()
const emit = defineEmits<{ select: [item: CatalogItem]; quantity: [item: CatalogItem, value: number]; arranged: []; editingChange: [value: boolean] }>()
const layout = useCatalogLayout()
const { editing, busy, error } = layout
const pointer = useCatalogPointer(layout.move, () => editing.value && !busy.value && !!props.canArrange)
const activeKind = ref<CatalogFilterKind>('all')
const keyword = ref('')
const categories = computed(() => [...new Set(visibleCatalog(props.items, { kind: activeKind.value, category: '', keyword: '' }).map(row => row.category))])
const category = ref('')
const visible = computed(() => {
  const rows = visibleCatalog(props.items, { kind: editing.value ? 'all' : activeKind.value, category: editing.value ? '' : category.value, keyword: editing.value ? '' : keyword.value })
  return editing.value ? rows.sort((a, b) => layout.ids.value.indexOf(a.id) - layout.ids.value.indexOf(b.id)) : rows
})
function selected(itemId: string) { return props.quantities[itemId] || 0 }
function unavailable(item: CatalogItem) { return !!props.disabled || (!props.manualInventory && item.stock_tracked && Number(item.stock_quantity) <= 0) }
function choose(item: CatalogItem) { if (!editing.value && !unavailable(item)) emit('select', item) }
async function begin() { await layout.begin(); if (editing.value) { activeKind.value = 'all'; category.value = ''; keyword.value = '' } }
async function save() { await layout.save(); if (!editing.value && !error.value) emit('arranged') }
function shift(id: string, direction: number) {
  const ids = layout.ids.value; const index = ids.indexOf(id)
  if (direction < 0 && index > 0) layout.move(id, ids[index - 1]!)
  if (direction > 0 && index >= 0 && index < ids.length - 1) layout.move(ids[index + 1]!, id)
}
watch(() => props.items.filter(item => item.is_active && ['service','product','package'].includes(item.kind)).map(item => item.id).sort().join('|'), () => layout.membersChanged())
watch(editing, value => emit('editingChange', value))
</script>

<template>
  <div v-if="canArrange" class="layout-toolbar"><el-button v-if="!editing" data-testid="arrange-start" :loading="busy" @click="begin">调整排列</el-button><template v-else><span>拖动手柄，或使用上移/下移</span><el-button data-testid="arrange-cancel" :disabled="busy" @click="layout.cancel()">取消</el-button><el-button data-testid="arrange-save" type="primary" :loading="busy" @click="save">保存排列</el-button></template></div>
  <el-alert v-if="error" :title="error" type="warning" :closable="false" />
  <div v-if="!editing" class="picker-toolbar">
    <el-radio-group v-model="activeKind" @change="category = ''"><el-radio-button value="all">全部</el-radio-button><el-radio-button value="service">服务</el-radio-button><el-radio-button value="product">商品</el-radio-button></el-radio-group>
    <el-input v-model="keyword" clearable placeholder="搜索项目" prefix-icon="Search" />
  </div>
  <div v-if="!editing && categories.length > 1" class="category-row"><button :class="{ active: !category }" @click="category = ''">全部</button><button v-for="name in categories" :key="name" :class="{ active: category === name }" @click="category = name">{{ name }}</button></div>
  <el-empty v-if="!visible.length" description="没有符合条件的可售项目" />
  <div class="catalog-grid">
    <article v-for="item in visible" :key="item.id" :data-catalog-id="item.id" :class="{ selected: !editing && selected(item.id), disabled: !editing && unavailable(item) }" role="button" :tabindex="editing || unavailable(item) ? -1 : 0" :aria-disabled="!editing && unavailable(item)" :aria-pressed="!!selected(item.id)" @click="choose(item)" @keydown.enter.prevent.self="choose(item)" @keydown.space.prevent.self="choose(item)">
      <div v-if="editing" class="layout-actions" @click.stop @keydown.stop><button class="drag-handle" :aria-label="`拖动${item.name}`" :disabled="busy" @pointerdown.stop.prevent="pointer.start($event, item.id)" @pointerup.stop="pointer.finish" @pointercancel="pointer.cancel">⠿</button><button :aria-label="`上移${item.name}`" :disabled="busy || layout.ids.value[0] === item.id" @click="shift(item.id,-1)">上移</button><button :aria-label="`下移${item.name}`" :disabled="busy || layout.ids.value.at(-1) === item.id" @click="shift(item.id,1)">下移</button></div>
      <span v-if="selected(item.id)" class="selection-mark"><el-icon><Check /></el-icon>{{ item.kind === 'product' ? `${selected(item.id)} 件` : '已选' }}</span>
      <strong>{{ item.name }}</strong><span>{{ item.category }}</span><small v-if="item.kind === 'package'">一人一份，仅已点包含项目免单项费</small><b>¥{{ item.price }}</b><small v-if="!manualInventory && item.stock_tracked">原销售单位库存 {{ item.stock_quantity }}</small>
      <el-input-number v-if="!editing && item.kind === 'product'" :disabled="unavailable(item)" :model-value="selected(item.id)" :min="0" :max="!manualInventory && item.stock_tracked ? Math.max(0, Math.floor(Number(item.stock_quantity))) : 99" :precision="0" size="small" @click.stop @keydown.stop @update:model-value="emit('quantity', item, Number($event || 0))" />
    </article>
  </div>
</template>

<style scoped>
.picker-toolbar { display: grid; grid-template-columns: auto minmax(150px, 230px); justify-content: space-between; gap: 10px; }
.category-row { display: flex; gap: 7px; margin: 12px 0; overflow-x: auto; }
.category-row button { padding: 6px 10px; color: var(--xq-text-2); cursor: pointer; border: 1px solid var(--xq-border); border-radius: 99px; background: white; white-space: nowrap; }
.category-row button.active { color: var(--xq-primary); border-color: var(--xq-primary); background: var(--xq-primary-soft); }
.catalog-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 11px; margin-top: 12px; }
article { position: relative; display: flex; flex-direction: column; gap: 5px; min-height: 112px; padding: 12px; cursor: pointer; border: 1px solid var(--xq-border); border-radius: var(--xq-radius-md); background: white; transition: .16s; }
article:hover { border-color: var(--xq-accent); background: #f3fcfa; }
article.selected { border: 2px solid var(--xq-accent); background: var(--xq-accent-soft); box-shadow: 0 0 0 3px rgba(15,159,143,.11); }
article.disabled { opacity: .46; cursor: not-allowed; }
article:focus-visible { outline: 2px solid var(--xq-primary); outline-offset: 2px; }
article strong { color: var(--xq-text-1); font-size: 16px; } article span, article small { color: var(--xq-text-3); } article b { color: var(--xq-danger); font-size: 17px; }
.selection-mark { position: absolute; top: 7px; right: 7px; display: inline-flex; align-items: center; gap: 2px; padding: 2px 6px; color: white !important; border-radius: 99px; background: var(--xq-accent); font-size: 10px; }
.el-input-number { width: 100%; margin-top: auto; }
.layout-toolbar, .layout-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
.layout-actions button { padding: 5px 7px; border: 1px solid var(--xq-border); background: white; border-radius: 5px; cursor: pointer; }
.layout-actions .drag-handle { touch-action: none; cursor: grab; font-size: 20px; }
@media (max-width: 1100px) { .catalog-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 600px) { .picker-toolbar { grid-template-columns: 1fr; } }
</style>
