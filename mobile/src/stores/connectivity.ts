import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { onBusinessSessionClear } from '../business/state'

export const useConnectivityStore = defineStore('mobile-connectivity', () => {
  const browserOnline = ref(navigator.onLine)
  const apiReachable = ref(true)
  const socketConnected = ref(false)
  const lastSyncAt = ref<number | null>(null)
  onBusinessSessionClear(() => { lastSyncAt.value = null; socketConnected.value = false; apiReachable.value = false })
  const canWrite = computed(() => browserOnline.value && apiReachable.value)
  const syncLabel = computed(() => lastSyncAt.value ? new Date(lastSyncAt.value).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : '尚未同步')
  function markSynced() { lastSyncAt.value = Date.now(); apiReachable.value = true }
  return { apiReachable, browserOnline, canWrite, lastSyncAt, markSynced, socketConnected, syncLabel }
})
