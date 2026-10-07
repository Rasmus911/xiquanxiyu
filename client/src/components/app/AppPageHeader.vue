<script setup lang="ts">
defineProps<{ title: string; description?: string; eyebrow?: string }>()
</script>
<template>
  <header class="app-page-header">
    <div><h1>{{ title }}</h1><p v-if="description">{{ description }}</p></div>
    <div class="page-actions"><slot name="actions" /></div>
  </header>
</template>
<style scoped>
.app-page-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
h1 { margin: 0; color: var(--xq-text-1); font-size: 22px; font-weight: 650; }
p { margin: 5px 0 0; color: var(--xq-text-3); font-size: 13px; }
.page-actions { display: flex; flex-wrap: wrap; gap: 8px; }
</style>
