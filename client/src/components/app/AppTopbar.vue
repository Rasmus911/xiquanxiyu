<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { resolveBackTarget } from '../../router/back-target'
import { useAuthStore } from '../../stores/auth'
import { useRuntimeStore } from '../../stores/runtime'

defineProps<{ online: boolean }>()
const auth = useAuthStore()
const runtime = useRuntimeStore()
const route = useRoute()
const router = useRouter()
const canReturn = computed(() => Boolean(route.meta.parentRoute || route.query.returnTo))
const updateLabel = computed(() => {
  const state = runtime.updateState
  if (!state) return ''
  if (state.status === 'downloaded') return `新版 ${state.availableVersion} 已就绪`
  if (state.status === 'downloading') return `下载更新 ${state.percent}%`
  if (state.required) return '需要更新'
  return ''
})
function goBack() { void router.push(resolveBackTarget(route)) }
function keyboardHelp() { window.dispatchEvent(new KeyboardEvent('keydown', { key: 'F1' })) }
</script>

<template>
  <header class="app-topbar">
    <div class="route-context">
      <el-button v-if="canReturn" circle plain aria-label="返回" @click="goBack"><el-icon><ArrowLeft /></el-icon></el-button>
      <div><span>{{ route.meta.section || '溪泉洗浴' }}</span><strong>{{ route.meta.title || '营业工作台' }}</strong></div>
    </div>
    <div class="topbar-actions">
      <div class="connection-pill" :class="online ? 'online' : 'offline'"><i></i>{{ online ? '实时同步' : '正在重连' }}</div>
      <el-button link @click="keyboardHelp">快捷键 F1</el-button>
      <el-button v-if="updateLabel" type="primary" plain size="small" @click="runtime.openUpdateCenter()"><el-icon><Download /></el-icon>{{ updateLabel }}</el-button>
      <div class="operator"><span>{{ auth.employee?.display_name || auth.employee?.username }}</span><small>{{ auth.terminal?.name }}</small></div>
      <el-button link type="primary" @click="auth.logout()">退出</el-button>
    </div>
  </header>
</template>

<style scoped>
.app-topbar { height: 68px; display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 0 24px; border-bottom: 1px solid var(--xq-border); background: rgba(255, 255, 255, .94); backdrop-filter: blur(12px); }
.route-context, .topbar-actions { display: flex; align-items: center; gap: 12px; }
.route-context span, .route-context strong, .operator span, .operator small { display: block; }
.route-context span { color: var(--xq-text-3); font-size: 11px; }
.route-context strong { margin-top: 2px; color: var(--xq-text-1); font-size: 16px; }
.connection-pill { display: flex; align-items: center; gap: 7px; padding: 7px 10px; border-radius: 99px; font-size: 11px; font-weight: 750; }
.connection-pill i { width: 7px; height: 7px; border-radius: 50%; }
.connection-pill.online { color: #08796c; background: var(--xq-accent-soft); }
.connection-pill.online i { background: var(--xq-accent); }
.connection-pill.offline { color: #a94930; background: #fff0eb; }
.connection-pill.offline i { background: #e15f3b; }
.operator { min-width: 88px; text-align: right; }
.operator span { color: var(--xq-text-1); font-size: 13px; font-weight: 750; }
.operator small { margin-top: 2px; color: var(--xq-text-3); font-size: 10px; }
</style>
