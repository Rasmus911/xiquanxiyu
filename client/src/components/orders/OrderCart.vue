<script setup lang="ts">
import { computed } from 'vue'
import type { CatalogItem } from '../../types'

const props = defineProps<{ items: CatalogItem[]; quantities: Record<string, number>; adding: boolean; compact?: boolean; disabled?: boolean }>()
defineEmits<{ clear: []; submit: [] }>()
const selectedRows = computed(() => props.items.filter((item) => (props.quantities[item.id] || 0) > 0))
const kindCount = computed(() => selectedRows.value.length)
const unitCount = computed(() => selectedRows.value.reduce((sum, item) => sum + props.quantities[item.id], 0))
const amount = computed(() => selectedRows.value.reduce((sum, item) => sum + Number(item.price) * props.quantities[item.id], 0))
</script>

<template>
  <aside class="order-cart" :class="{ compact }">
    <div><span>本次待加</span><strong>{{ kindCount }} 种 · {{ unitCount }} 份</strong><small v-if="kindCount">预计 ¥{{ amount.toFixed(2) }}</small><small v-else>点击左侧服务或商品进行选择</small></div>
    <div class="cart-actions"><el-button :disabled="!unitCount || adding" @click="$emit('clear')">清空</el-button><el-button data-testid="submit-order" type="primary" :loading="adding" :disabled="!unitCount || adding || disabled" @click="$emit('submit')">确认加单</el-button></div>
  </aside>
</template>

<style scoped>
.order-cart { position: sticky; z-index: 8; bottom: 12px; display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 14px; padding: 12px 14px; color: white; border-radius: 12px; background: rgba(23,35,60,.96); box-shadow: 0 12px 30px rgba(23,35,60,.22); }
.order-cart span, .order-cart strong, .order-cart small { display: block; } .order-cart span { color: #b9c5d6; font-size: 10px; } .order-cart strong { margin-top: 2px; } .order-cart small { margin-top: 2px; color: #d8e0eb; }
.cart-actions { display: flex; gap: 8px; }
.order-cart.compact { position: static; z-index: auto; flex-wrap: wrap; justify-content: flex-end; margin: 0; padding: 0; color: var(--xq-text-1); background: transparent; border-radius: 0; box-shadow: none; }
.compact span, .compact small { color: var(--xq-text-3); }
.compact strong { font-size: 13px; white-space: nowrap; }
</style>
