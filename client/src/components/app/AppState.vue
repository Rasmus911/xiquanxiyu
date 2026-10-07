<script setup lang="ts">
defineProps<{ type: 'loading' | 'empty' | 'error' | 'forbidden'; title?: string; description?: string }>()
const defaults = {
  loading: ['正在读取', '请稍候，正在同步最新数据'],
  empty: ['暂无数据', '完成第一笔操作后会显示在这里'],
  error: ['读取失败', '请检查网络后重试'],
  forbidden: ['没有访问权限', '请联系管理员调整账号权限'],
}
</script>
<template>
  <div class="app-state"><div class="state-mark">{{ type === 'loading' ? '…' : type === 'empty' ? '○' : type === 'error' ? '!' : '×' }}</div><strong>{{ title || defaults[type][0] }}</strong><p>{{ description || defaults[type][1] }}</p><slot /></div>
</template>
<style scoped>
.app-state { min-height: 220px; display: grid; place-items: center; align-content: center; text-align: center; color: var(--xq-text-3); }
.state-mark { width: 48px; height: 48px; display: grid; place-items: center; margin-bottom: 12px; border-radius: 16px; color: var(--xq-primary); background: var(--xq-primary-soft); font-size: 24px; font-weight: 850; }
strong { color: var(--xq-text-1); font-size: 16px; }
p { margin: 6px 0 14px; font-size: 12px; }
</style>
