<script setup lang="ts">
import type { CatalogFilterKind } from '../../domain/catalog/filter'
defineProps<{ modelValue: CatalogFilterKind }>()
defineEmits<{ 'update:modelValue': [value: CatalogFilterKind] }>()
</script>
<template><div class="catalog-tabs"><button :class="{active:modelValue==='all'}" @click="$emit('update:modelValue','all')">全部</button><button :class="{active:modelValue==='service'}" @click="$emit('update:modelValue','service')">服务</button><button :class="{active:modelValue==='product'}" @click="$emit('update:modelValue','product')">商品</button></div></template>
<style scoped>.catalog-tabs{display:grid;grid-template-columns:repeat(3,1fr);padding:4px;border-radius:7px;background:#e9eef5}button{min-height:42px;border:0;border-radius:6px;color:var(--m-text-2);background:transparent;font-weight:700}button.active{color:var(--m-primary);background:white}</style>
