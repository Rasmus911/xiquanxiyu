<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { MobileCatalogItem } from '../../types'
import { visibleCatalog, type CatalogFilterKind } from '../../domain/catalog/filter'
import { useCatalogLayout } from '../../composables/useCatalogLayout'
import { useCatalogPointer } from '../../composables/useCatalogPointer'
const props = defineProps<{ items: MobileCatalogItem[]; quantities: Record<string, number>; kind: CatalogFilterKind; canArrange?: boolean }>()
const emit = defineEmits<{ select: [item: MobileCatalogItem]; change: [item: MobileCatalogItem, delta: number]; arranged: []; editingChange: [value: boolean] }>()
const layout = useCatalogLayout()
const { editing, busy, error } = layout
const pointer = useCatalogPointer(layout.move, () => editing.value && !busy.value && !!props.canArrange)
const search = ref(''); const category = ref('')
const categories = computed(() => [...new Set(visibleCatalog(props.items, { kind: props.kind, category: '', keyword: '' }).map(item => item.category))])
const visible = computed(() => {
  const rows = visibleCatalog(props.items, { kind: editing.value ? 'all' : props.kind, category: editing.value ? '' : category.value, keyword: editing.value ? '' : search.value })
  return editing.value ? rows.sort((a,b) => layout.ids.value.indexOf(a.id) - layout.ids.value.indexOf(b.id)) : rows
})
function unavailable(item: MobileCatalogItem) { return item.is_active === false }
function choose(item: MobileCatalogItem) { if (!editing.value && !unavailable(item)) emit('select', item) }
async function begin() { await layout.begin(); if (editing.value) { category.value = ''; search.value = '' } }
async function save() { await layout.save(); if (!editing.value && !error.value) emit('arranged') }
function shift(id: string, direction: number) {
  const ids = layout.ids.value; const index = ids.indexOf(id)
  if (direction < 0 && index > 0) layout.move(id, ids[index-1]!)
  if (direction > 0 && index >= 0 && index < ids.length-1) layout.move(ids[index+1]!, id)
}
watch(editing, value => emit('editingChange', value))
watch(() => props.items.map(item => item.id).sort().join('|'), () => layout.membersChanged())
watch(() => props.kind, () => { category.value = '' })
</script>
<template>
  <div v-if="canArrange" class="layout-toolbar"><button v-if="!editing" data-testid="arrange-start" :disabled="busy" @click="begin">调整排列</button><template v-else><span>拖动手柄或上移/下移</span><button data-testid="arrange-cancel" :disabled="busy" @click="layout.cancel()">取消</button><button data-testid="arrange-save" :disabled="busy" @click="save">{{busy?'保存中':'保存排列'}}</button></template></div>
  <div v-if="error" class="notice">{{error}}</div>
  <template v-if="!editing"><input v-model="search" class="mobile-input" placeholder="搜索项目" aria-label="搜索项目"/><div class="chips"><button :class="{active:!category}" @click="category=''">全部分类</button><button v-for="name in categories" :key="name" :class="{active:category===name}" @click="category=name">{{name}}</button></div></template>
  <div class="catalog-list"><article v-for="item in visible" :key="item.id" :data-catalog-id="item.id" :class="{selected:!editing&&quantities[item.id],disabled:!editing&&unavailable(item)}" role="button" :tabindex="editing||unavailable(item)?-1:0" :aria-disabled="!editing&&unavailable(item)" :aria-pressed="!!quantities[item.id]" @click="choose(item)" @keydown.enter.prevent.self="choose(item)" @keydown.space.prevent.self="choose(item)">
    <div><strong>{{item.name}}</strong><span>{{item.category}}</span></div><b>¥{{item.price}}</b>
    <div v-if="editing" class="layout-actions" @click.stop @keydown.stop><button class="drag-handle" :aria-label="`拖动${item.name}`" :disabled="busy" @pointerdown.stop.prevent="pointer.start($event,item.id)" @pointerup.stop="pointer.finish" @pointercancel="pointer.cancel">⠿</button><button :aria-label="`上移${item.name}`" :disabled="busy||layout.ids.value[0]===item.id" @click="shift(item.id,-1)">↑</button><button :aria-label="`下移${item.name}`" :disabled="busy||layout.ids.value.at(-1)===item.id" @click="shift(item.id,1)">↓</button></div>
    <span v-else-if="item.kind!=='product'" class="check">{{quantities[item.id]?'✓ 已选':'+ 选择'}}<small v-if="item.kind==='package'"> · 一人一份</small></span><div v-else class="stepper" @click.stop @keydown.stop><button :disabled="!quantities[item.id]" :aria-label="`减少${item.name}`" @click="emit('change',item,-1)">−</button><strong>{{quantities[item.id]||0}}</strong><button :disabled="unavailable(item)" :aria-label="`增加${item.name}`" @click="emit('change',item,1)">+</button></div>
  </article></div>
</template>
<style scoped>
.mobile-input{width:100%;min-height:46px;margin-top:12px;padding:0 14px;border:1px solid var(--m-border);border-radius:7px;background:white;outline:none}.mobile-input:focus{border-color:var(--m-primary)}
.chips{display:flex;gap:7px;margin:10px 0;overflow-x:auto;scrollbar-width:none}.chips::-webkit-scrollbar{display:none}.chips button{min-height:36px;padding:0 13px;border:1px solid var(--m-border);border-radius:6px;color:var(--m-text-2);background:white;white-space:nowrap}.chips button.active{color:var(--m-primary);border-color:var(--m-primary);background:var(--m-primary-soft)}
.catalog-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}article{display:flex;flex-direction:column;gap:10px;min-height:150px;padding:12px;border:1px solid var(--m-border);border-radius:8px;background:white}article.selected{border-color:var(--m-accent);background:var(--m-accent-soft)}article.disabled{opacity:.45}article strong,article span{display:block}article span{margin-top:4px;color:var(--m-text-3);font-size:12px}article>b{color:var(--m-danger);font-size:16px}
.check{margin-top:auto!important;padding:6px;color:var(--m-primary)!important;font-size:13px!important}.stepper{display:grid;grid-template-columns:1fr 32px 1fr;align-items:center;margin-top:auto;text-align:center}.stepper button{height:34px;border:0;border-radius:6px;color:var(--m-primary);background:var(--m-primary-soft);font-size:20px}.stepper button:disabled{opacity:.4}article:focus-visible{outline:2px solid var(--m-primary)}
.layout-toolbar,.layout-actions{display:flex;align-items:center;flex-wrap:wrap;gap:6px;margin:10px 0}.layout-toolbar button,.layout-actions button{min-height:36px;padding:4px 10px;border:1px solid var(--m-border);border-radius:5px;background:white;color:var(--m-primary)}.layout-actions .drag-handle{touch-action:none;font-size:24px}
</style>
