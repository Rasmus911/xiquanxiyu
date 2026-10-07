<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import AppSidebar from '../components/app/AppSidebar.vue'
import AppTopbar from '../components/app/AppTopbar.vue'
import OfflineBanner from '../components/app/OfflineBanner.vue'
import { startRealtime, stopRealtime } from '../composables/useRealtime'
import { useConnectivityStore } from '../stores/connectivity'
import { useRuntimeStore } from '../stores/runtime'
import { dispatchRealtimeSnapshot } from '../realtime/events'
import { resolveBackTarget } from '../router/back-target'
import { editableTarget, shortcutIntent } from '../navigation/shortcuts'

const connectivity = useConnectivityStore()
const { isOnline } = storeToRefs(connectivity)
const route = useRoute()
const router = useRouter()
const runtime = useRuntimeStore()
const helpOpen = ref(false)

function handleKey(event: KeyboardEvent) {
  const modal = [...document.querySelectorAll<HTMLElement>('[role="dialog"], .el-overlay')]
    .some(node => node.getClientRects().length > 0)
  const canReturn = Boolean(route.meta.parentRoute || route.query.returnTo)
  const intent = shortcutIntent(event, {
    editable: editableTarget(event.target),
    modal, busy: Boolean(runtime.businessBusyReason), canReturn,
  })
  if (!intent) return
  event.preventDefault()
  if (intent === 'help') helpOpen.value = true
  if (intent === 'search') {
    const input = document.querySelector<HTMLInputElement>('.app-main [data-search] input, .app-main input[placeholder*="搜索"], .app-main input[placeholder*="手牌号"], .app-main input[placeholder*="手机号"], .app-main input[placeholder*="账号"]')
    input?.focus(); input?.select()
  }
  if (intent === 'refresh') {
    dispatchRealtimeSnapshot()
    window.dispatchEvent(new Event('xiquan:refresh-page'))
  }
  if (intent === 'escape') {
    const cancel = new Event('xiquan:cancel-selection', { cancelable: true })
    if (!window.dispatchEvent(cancel)) return
  }
  if (intent === 'back' || (intent === 'escape' && canReturn)) void router.push(resolveBackTarget(route))
}

onMounted(() => { startRealtime(); window.addEventListener('keydown', handleKey) })

onBeforeUnmount(() => { stopRealtime(); window.removeEventListener('keydown', handleKey) })
</script>

<template>
  <div class="app-shell">
    <AppSidebar />
    <section class="app-workspace">
      <AppTopbar :online="isOnline" />
      <OfflineBanner :online="isOnline" />
      <main class="app-main"><router-view /></main>
    </section>
  </div>
  <el-dialog v-model="helpOpen" title="键盘操作" width="440px">
    <p>Ctrl+C / V / X：复制、粘贴、剪切</p><p>Ctrl+A / Z / Y：全选、撤销、重做</p>
    <p>F2：定位搜索　F5 / Ctrl+R：刷新当前数据</p><p>Tab：切换焦点　Enter / 空格：打开聚焦的手牌</p>
    <p>Esc：关闭弹窗或取消批量选择　Alt+←：返回上级</p>
    <p class="muted">提交收款、充值或入库期间暂停页面快捷操作。</p>
  </el-dialog>
</template>

<style scoped>
.app-shell { min-height: 100vh; display: flex; }
.app-workspace { min-width: 0; flex: 1; }
.app-main { min-height: calc(100vh - 68px); }
</style>
